"""Runtime configuration (environment variables)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _i(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _b(name: str, default: bool) -> bool:
    return os.environ.get(name, str(int(default))).lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("IMG2LIVE_DATA", "./data")).resolve())
    # --- limits
    max_upload_mb: int = field(default_factory=lambda: _i("IMG2LIVE_MAX_UPLOAD_MB", 12))
    max_pixels: int = field(default_factory=lambda: _i("IMG2LIVE_MAX_PIXELS", 16_000_000))
    min_side: int = field(default_factory=lambda: _i("IMG2LIVE_MIN_SIDE", 256))
    max_queue: int = field(default_factory=lambda: _i("IMG2LIVE_MAX_QUEUE", 8))
    per_ip_per_day: int = field(default_factory=lambda: _i("IMG2LIVE_PER_IP_PER_DAY", 3))
    retention_hours: float = field(default_factory=lambda: _f("IMG2LIVE_RETENTION_HOURS", 72))
    # --- access
    access_code: str = field(default_factory=lambda: os.environ.get("IMG2LIVE_ACCESS_CODE", ""))
    trust_proxy: bool = field(default_factory=lambda: _b("IMG2LIVE_TRUST_PROXY", False))
    ip_salt: str = field(default_factory=lambda: os.environ.get("IMG2LIVE_IP_SALT", "change-me"))
    contact_url: str = field(default_factory=lambda: os.environ.get("IMG2LIVE_CONTACT_URL", "https://github.com/CocoRoF/img2live/issues"))
    # --- safety gate (WD tagger v3)
    gate_enabled: bool = field(default_factory=lambda: _b("IMG2LIVE_GATE", True))
    gate_nsfw: float = field(default_factory=lambda: _f("IMG2LIVE_GATE_NSFW", 0.50))
    gate_minor_tag: float = field(default_factory=lambda: _f("IMG2LIVE_GATE_MINOR_TAG", 0.35))
    gate_minor_sensitive: float = field(default_factory=lambda: _f("IMG2LIVE_GATE_MINOR_SENSITIVE", 0.50))
    gate_photo: float = field(default_factory=lambda: _f("IMG2LIVE_GATE_PHOTO", 0.60))
    gate_multi: float = field(default_factory=lambda: _f("IMG2LIVE_GATE_MULTI", 0.60))
    # --- engine
    engine: str = field(default_factory=lambda: os.environ.get("IMG2LIVE_ENGINE", "layerdiff"))  # layerdiff | fake
    quant: str = field(default_factory=lambda: os.environ.get("IMG2LIVE_QUANT", "nf4"))
    group_offload: bool = field(default_factory=lambda: _b("IMG2LIVE_GROUP_OFFLOAD", True))
    steps: int = field(default_factory=lambda: _i("IMG2LIVE_STEPS", 30))
    retries: int = field(default_factory=lambda: _i("IMG2LIVE_RETRIES", 1))  # extra decomposition attempts on a severe layer leak

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "img2live.sqlite3"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.jobs_dir, self.models_dir):
            d.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
