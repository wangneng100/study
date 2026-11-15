"""Settings, read from environment variables and an optional .env file."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path = ROOT / ".env") -> None:
    """Read KEY=value lines from .env. Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def settings() -> dict:
    load_env()
    return {
        "DB_PATH": os.environ.get("STUDY_DB") or str(ROOT / "instance" / "study.db"),
        "PORT": int(os.environ.get("PORT", "8765")),
        # auto: 1min.ai when a key is set, otherwise Google Translate.
        "TRANSLATOR": os.environ.get("TRANSLATOR", "auto").strip().lower(),
        "ONEMIN_API_KEY": os.environ.get("ONEMIN_API_KEY", "").strip(),
        "ONEMIN_MODEL": os.environ.get("ONEMIN_MODEL", "gpt-4o-mini").strip(),
    }
