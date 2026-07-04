"""Central configuration: env credentials + user-tunable settings.

User settings persist to data/settings.json and are editable from the
dashboard. Env vars (Schwab credentials) come from .env.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"
TOKEN_FILE = DATA_DIR / "schwab_token.json"
DB_FILE = DATA_DIR / "journal.db"
HISTORY_DIR = DATA_DIR / "history"

load_dotenv(PROJECT_ROOT / ".env")

# MNQ contract math
POINT_VALUE = 2.0          # $ per point per contract
TICK_SIZE = 0.25           # points
TICK_VALUE = 0.50          # $ per tick per contract


@dataclass
class Settings:
    """User-tunable settings, persisted to data/settings.json."""

    # Risk
    risk_a_grade: float = 150.0     # $ risk for A-grade setups
    risk_b_grade: float = 100.0     # $ risk for B-grade setups
    max_contracts: int = 2
    account_size: float = 1200.0
    circuit_breaker_losses: int = 2  # stopped-out signals per day before lockout
    circuit_breaker_enabled: bool = True

    # Signal behaviour
    score_fire_b: float = 3.0       # min confluence score to fire a B-grade call
    score_fire_a: float = 4.5       # min confluence score for an A-grade call
    signal_cooldown_sec: int = 180  # min seconds between signals
    signal_ttl_sec: int = 90        # entry expires if not acted on
    max_signal_age_min: int = 45    # open signal resolved at market after this

    # Sessions (ET)
    rth_only: bool = True           # only fire during regular trading hours
    no_open_minutes: int = 5        # quiet minutes right after 9:30 open
    lunch_a_grade_only: bool = True # 12:00-13:30 requires A-grade
    last_entry_minutes: int = 15    # no new signals in final N minutes before 16:00

    # Dashboard
    sound_enabled: bool = True

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> "Settings":
        if SETTINGS_FILE.exists():
            try:
                raw = json.loads(SETTINGS_FILE.read_text())
                known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
                return cls(**known)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def update(self, patch: dict) -> None:
        for key, value in patch.items():
            if key in self.__dataclass_fields__:
                current = getattr(self, key)
                setattr(self, key, type(current)(value))
        self.save()


@dataclass
class SchwabCredentials:
    app_key: str = field(default_factory=lambda: os.getenv("SCHWAB_APP_KEY", ""))
    app_secret: str = field(default_factory=lambda: os.getenv("SCHWAB_APP_SECRET", ""))
    callback_url: str = field(
        default_factory=lambda: os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")
    )

    @property
    def configured(self) -> bool:
        return bool(self.app_key and self.app_secret
                    and "your-app-key" not in self.app_key)
