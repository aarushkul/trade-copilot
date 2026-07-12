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

_env = PROJECT_ROOT / ".env"
_example = PROJECT_ROOT / ".env.example"
if _env.exists():
    load_dotenv(_env)
elif _example.exists():
    load_dotenv(_example)  # convenience if user only filled .env.example

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

    # Trading friction, applied to every tracked signal so journal stats are
    # net (what you'd actually keep), not gross.
    commission_per_side: float = 0.74  # $ per contract per fill (broker+exchange+NFA)
    slippage_ticks: int = 1            # ticks lost per market-order fill

    # Signal behaviour
    score_fire_b: float = 4.0       # min confluence score to fire a B-grade call
    score_fire_a: float = 4.5       # min confluence score for an A-grade call
    strict_choch: bool = True       # CHoCH requires a prior opposite trend
                                    # (False = also fires on ranging-bias breaks)
    signal_cooldown_sec: int = 180  # min seconds between signals
    signal_ttl_sec: int = 90        # entry expires if not acted on
    max_signal_age_min: int = 45    # open signal resolved at market after this
    target2_r: float = 2.0          # runner target in R multiples

    # Selectivity mode (2026-07-12, from the research program): every entry
    # pays a measured 0.03-0.13 R toll (1,680-session tod study), so fewer,
    # higher-bar calls dominate. Zero-signal days are a feature.
    a_grade_only: bool = True       # B-grade confluence is context, never a call
    daily_signal_cap: int = 2       # hard cap on calls per session

    # Sessions (ET)
    rth_only: bool = True           # only fire during regular trading hours
    no_open_minutes: int = 30       # 09:30-10:00 measured worst bucket both
                                    # directions (t <= -2.5 all bracket arms)
    lunch_a_grade_only: bool = True # 12:00-13:30 requires A-grade
    last_entry_minutes: int = 60    # 15:00+ measured worst for longs (t -4.4)
                                    # and 15:30+ bad both ways

    # Dashboard
    sound_enabled: bool = True

    # Floors for settings where a too-small value breaks the engine
    # (e.g. breaker_losses=0 would trip the breaker with zero losses).
    _MIN_VALUES = {
        "circuit_breaker_losses": 1,
        "max_contracts": 1,
        "signal_ttl_sec": 15,
        "max_signal_age_min": 1,
        "daily_signal_cap": 1,
    }

    def _clamp(self) -> None:
        for key, floor in self._MIN_VALUES.items():
            if getattr(self, key) < floor:
                setattr(self, key, floor)

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> "Settings":
        if SETTINGS_FILE.exists():
            try:
                raw = json.loads(SETTINGS_FILE.read_text())
                known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
                settings = cls(**known)
                settings._clamp()
                return settings
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def update(self, patch: dict) -> None:
        for key, value in patch.items():
            if key in self.__dataclass_fields__:
                current = getattr(self, key)
                setattr(self, key, type(current)(value))
        self._clamp()
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
