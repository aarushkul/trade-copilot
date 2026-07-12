"""Runtime wiring: feed -> engine -> journal -> hub, plus chart bar cache."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Optional

from app.config import DB_FILE, DATA_DIR, Settings, SchwabCredentials
from app.engine.engine import SignalEngine
from app.journal.journal import Journal
from app.models import Bar, Quote, Signal
from app.server.api import Hub

log = logging.getLogger("runtime")


class Runtime:
    def __init__(self, feed_mode: str = "sim"):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.feed_mode = feed_mode
        self.settings = Settings.load()
        self.settings.save()
        self.engine = SignalEngine(self.settings)
        self.journal = Journal(DB_FILE, self.settings, self.engine.breaker,
                               source="sim" if feed_mode == "sim" else "live")
        self.hub = Hub()
        self.feed = None
        self.symbol = "SIM/MNQ"
        self.shutdown_event = asyncio.Event()

        # Wire callbacks.
        self.engine.on_state = self._on_state
        self.engine.on_signal = self._on_signal
        self.journal.on_update = self._on_signal_update

    # -- feed construction -----------------------------------------------------

    def build_feed(self):
        if self.feed_mode == "schwab":
            from app.feed.schwab_feed import SchwabFeed
            creds = SchwabCredentials()
            if not creds.configured:
                raise RuntimeError(
                    "Schwab credentials missing. Copy .env.example to .env and "
                    "fill in SCHWAB_APP_KEY / SCHWAB_APP_SECRET, then run "
                    ".venv/bin/python scripts/schwab_login.py")
            self.feed = SchwabFeed(creds)
            self.symbol = self.feed.symbol
            # 25 calendar days ≈ 17 sessions: enough to prime the 14-session
            # noise bands as well as levels/indicators.
            bars = self.feed.fetch_history(days=25)
            if bars:
                self.engine.seed_history(bars)
        else:
            from app.feed.sim_feed import SimFeed, generate_history
            self.feed = SimFeed()
            self.engine.demo_override = True
            bars = generate_history(days=10, seed=7)
            if bars:
                self.feed.price = bars[-1].close
                self.engine.seed_history(bars)
            log.info("sim feed seeded with %d synthetic 1m bars", len(bars))
        return self.feed

    def feed_stale(self) -> bool:
        return bool(getattr(self.feed, "is_stale", False))

    # -- event plumbing -----------------------------------------------------------

    def on_quote(self, q: Quote) -> None:
        """Single entry point for every tick, regardless of feed."""
        self.journal.on_quote(q)
        self.engine.active_signal = self.journal.open_signal
        self.engine.on_quote(q)
        forming = self.engine.bars.series["1m"].forming
        if forming is not None:
            self.hub.broadcast({"type": "bar", "tf": "1m",
                                "bar": forming.to_dict(), "forming": True})

    def _on_state(self, state: dict) -> None:
        state["type"] = "state"
        state["open_signal"] = (self.journal.open_signal.to_dict()
                                if self.journal.open_signal else None)
        self.hub.broadcast(state)

    def _on_signal(self, signal: Signal) -> None:
        self.journal.record(signal)
        self.engine.active_signal = signal
        log.info("SIGNAL %s %s x%d @ %.2f stop %.2f t1 %.2f (%s)",
                 signal.grade.value, signal.direction.value, signal.contracts,
                 signal.entry, signal.stop, signal.target1, signal.setup_type)
        self.hub.broadcast({"type": "signal", "signal": signal.to_dict(),
                            "stats_today": self.journal.today_stats()})

    def _on_signal_update(self, signal: Signal) -> None:
        if self.journal.open_signal is None:
            self.engine.active_signal = None
        self.hub.broadcast({"type": "signal_update", "signal": signal.to_dict(),
                            "stats_today": self.journal.today_stats(),
                            "stats_all": self.journal.stats()})

    # -- dashboard helpers -----------------------------------------------------------

    def settings_dict(self) -> dict:
        return asdict(self.settings)

    def chart_bars(self, limit: int = 240) -> list[dict]:
        series = self.engine.bars.series["1m"]
        bars = [b.to_dict() for b in series.last_bars(limit)]
        if series.forming is not None:
            bars.append(series.forming.to_dict())
        return bars
