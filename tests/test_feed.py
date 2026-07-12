"""Schwab feed warm-up resilience: cache fallback when the API fails."""
import time

from app.config import SchwabCredentials
from app.feed.schwab_feed import SchwabFeed
from app.models import Bar


def _feed(tmp_path):
    feed = SchwabFeed(SchwabCredentials())
    feed.cache_file = tmp_path / "warmup_cache.json"

    def boom():
        raise ConnectionError("no network in tests")

    feed._make_client = boom
    return feed


def _bars(n=50):
    base = time.time() - n * 60
    return [Bar(base + i * 60, 100.0, 101.0, 99.0, 100.5, 10) for i in range(n)]


def test_fetch_history_falls_back_to_cache(tmp_path):
    feed = _feed(tmp_path)
    # No cache yet: total failure yields empty (engine warms from live only).
    assert feed.fetch_history(days=5) == []

    feed._save_cache(_bars())
    got = feed.fetch_history(days=5)
    assert len(got) == 50
    assert got[0].close == 100.5


def test_cache_rejected_after_contract_roll(tmp_path):
    feed = _feed(tmp_path)
    feed._save_cache(_bars())
    feed.symbol = "/MNQZ99"  # front month rolled since the cache was written
    assert feed.fetch_history(days=5) == []
