"""Environment-only deployment configuration. No model downloads at runtime."""
from dataclasses import dataclass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

@dataclass
class Settings:
    environment: str = "development"
    database_url: str = f"sqlite:///{(ROOT / 'runtime' / 'ember.db').as_posix()}"
    model_path: Path = ROOT / "models" / "best.pt"
    policy_path: Path = ROOT / "models" / "fire_policy_v1.json"
    storage_path: Path = ROOT / "runtime" / "evidence"
    samples_path: Path = ROOT / "samples"
    admin_name: str = "admin"
    admin_password: str = "fire-demo-local"
    public_origin: str = "http://localhost:5173"
    local_console_enabled: bool = True
    device: str = "cpu"
    secure_cookie: bool = False
    session_hours: int = 12
    max_frame_bytes: int = 2_000_000
    max_pixels: int = 16_000_000
    max_cameras: int = 8
    alarm_hits: int = 3
    alarm_window: int = 5
    alarm_min_seconds: float = 1.0
    frame_gap_seconds: float = 4.0
    alarm_clear_frames: int = 5
    alarm_cooldown_seconds: float = 30.0
    storage_backend: str = "local"
    s3_bucket: str = ""
    demo_enabled: bool = True
    torch_threads: int = 4
    spread_data_path: Path = ROOT / "runtime" / "spread-data"
    spread_jobs_path: Path = ROOT / "runtime" / "spread-jobs"
    cctv_ai_approved: bool = False
    monitor_capacity: int = 4

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        values = {}
        for key, field in cls.__dataclass_fields__.items():
            raw = os.getenv("EMBER_" + key.upper())
            if raw is None:
                continue
            default = field.default
            if isinstance(default, bool):
                values[key] = raw.lower() in ("1", "true", "yes")
            elif isinstance(default, Path):
                values[key] = Path(raw)
            elif isinstance(default, int):
                values[key] = int(raw)
            elif isinstance(default, float):
                values[key] = float(raw)
            else:
                values[key] = raw
        result = cls(**values)
        if not 1 <= result.alarm_hits <= result.alarm_window <= 20:
            raise ValueError("Invalid temporal alarm window")
        if not 1 <= result.monitor_capacity <= min(8,result.max_cameras):
            raise ValueError("Monitor capacity must be 1..min(8,max_cameras)")
        if result.environment == "production":
            if len(result.admin_password) < 16 or result.admin_password == "fire-demo-local":
                raise ValueError("Production requires a unique 16+ character admin password")
            if not result.public_origin.startswith("https://") or not result.secure_cookie:
                raise ValueError("Production requires HTTPS origin and secure cookies")
            if not result.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")
            if result.demo_enabled:
                raise ValueError("Disable demonstration sample endpoints in production")
        return result
