"""Schwab Trader API connector.

Live: streams LEVELONE_FUTURES for the MNQ front month over Schwab's WebSocket.
Warm-up: pulls recent 1m bars from the price-history REST endpoint.
Requires: .env with SCHWAB_APP_KEY/SECRET and a one-time login via
`python scripts/schwab_login.py` (writes data/schwab_token.json).
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import time
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from app.config import TOKEN_FILE, SchwabCredentials
from app.models import Bar, Quote

log = logging.getLogger("schwab_feed")

# CME quarterly cycle for equity index futures.
QUARTER_MONTHS = [3, 6, 9, 12]
MONTH_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}


def third_friday(year: int, month: int) -> date:
    cal = calendar.Calendar()
    fridays = [d for d in cal.itermonthdates(year, month)
               if d.month == month and d.weekday() == 4]
    return fridays[2]


def front_month_symbol(today: Optional[date] = None, root: str = "/MNQ") -> str:
    """Front-month contract symbol, rolling 8 days before expiry."""
    d = today or date.today()
    for offset in range(0, 6):
        idx = (d.month - 1) // 3 + offset
        year = d.year + idx // 4
        month = QUARTER_MONTHS[idx % 4]
        expiry = third_friday(year, month)
        if d <= expiry - timedelta(days=8):
            return f"{root}{MONTH_CODES[month]}{year % 100:02d}"
    raise RuntimeError("could not resolve front month")


def _field(item: dict, label: str, num: str):
    """schwab-py labels fields when it can; fall back to numeric keys."""
    if label in item:
        return item[label]
    return item.get(num)


class SchwabFeed:
    STALE_SECONDS = 45

    def __init__(self, creds: SchwabCredentials):
        self.creds = creds
        self.symbol = front_month_symbol()
        self._client = None
        self._last_quote_ts = 0.0
        self._running = False

    # -- client -----------------------------------------------------------------

    def _make_client(self):
        from schwab.auth import client_from_token_file
        if not TOKEN_FILE.exists():
            raise RuntimeError(
                "No Schwab token found. Run: .venv/bin/python scripts/schwab_login.py")
        return client_from_token_file(
            api_key=self.creds.app_key,
            app_secret=self.creds.app_secret,
            token_path=str(TOKEN_FILE),
        )

    # -- history -----------------------------------------------------------------

    def fetch_history(self, days: int = 10) -> list[Bar]:
        """Recent 1m bars for indicator warm-up. Empty list on failure."""
        try:
            client = self._client or self._make_client()
            end = datetime.now()
            start = end - timedelta(days=days)
            resp = client.get_price_history_every_minute(
                self.symbol, start_datetime=start, end_datetime=end,
                need_extended_hours_data=True)
            resp.raise_for_status()
            candles = resp.json().get("candles", [])
            bars = [Bar(c["datetime"] / 1000.0, c["open"], c["high"],
                        c["low"], c["close"], int(c.get("volume", 0)))
                    for c in candles]
            log.info("history warm-up: %d 1m bars for %s", len(bars), self.symbol)
            return bars
        except Exception as exc:  # noqa: BLE001 - feed must never crash the app
            log.warning("history fetch failed (%s); warming from live only", exc)
            return []

    # -- live stream ---------------------------------------------------------------

    async def run(self, on_quote: Callable[[Quote], None]) -> None:
        """Stream with auto-reconnect. Never returns unless stop() is called."""
        from schwab.streaming import StreamClient

        self._running = True
        backoff = 2
        while self._running:
            try:
                self._client = self._make_client()
                stream = StreamClient(self._client)
                await stream.login()

                def handler(msg: dict) -> None:
                    for item in msg.get("content", []):
                        last = _field(item, "LAST_PRICE", "3")
                        if last is None:
                            continue
                        bid = _field(item, "BID_PRICE", "1") or 0.0
                        ask = _field(item, "ASK_PRICE", "2") or 0.0
                        size = _field(item, "LAST_SIZE", "9") or 0
                        vol = _field(item, "TOTAL_VOLUME", "8") or 0
                        self._last_quote_ts = time.time()
                        on_quote(Quote(ts=self._last_quote_ts, last=float(last),
                                       bid=float(bid), ask=float(ask),
                                       last_size=int(size), day_volume=int(vol)))

                stream.add_level_one_futures_handler(handler)
                await stream.level_one_futures_subs([self.symbol])
                log.info("streaming %s", self.symbol)
                backoff = 2

                while self._running:
                    try:
                        await asyncio.wait_for(stream.handle_message(), timeout=30)
                    except asyncio.TimeoutError:
                        if (time.time() - self._last_quote_ts > self.STALE_SECONDS
                                and self._last_quote_ts > 0):
                            raise ConnectionError("feed stale, reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("stream error: %s - reconnecting in %ds", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def stop(self) -> None:
        self._running = False

    @property
    def is_stale(self) -> bool:
        return (self._last_quote_ts > 0
                and time.time() - self._last_quote_ts > self.STALE_SECONDS)
