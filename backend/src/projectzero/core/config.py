"""Settings from the environment, with the repository's ``.env`` as a fallback (never overriding real env vars)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from projectzero.core.paths import REPO_ROOT

_LINE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$")


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Minimal .env reader: KEY=VALUE lines, '#' comments, no interpolation. Existing env vars win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#") or not (match := _LINE.match(line)):
            continue
        key, value = match.groups()
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    db_url: str = field(repr=False)  # contains the database password: never in repr, logs or test failure output
    schema: str = "pz"
    host: str = "127.0.0.1"
    port: int = 8177

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        db_url = os.environ.get("SUPABASE_DB_URL", "")
        if not db_url:
            raise RuntimeError("SUPABASE_DB_URL is not set (session pooler, port 5432) — see .env.example")
        if ":6543/" in db_url:
            raise RuntimeError("SUPABASE_DB_URL points at the transaction pooler (6543); use the session pooler (5432)")
        return cls(
            db_url=db_url,
            schema=os.environ.get("PZ_SCHEMA", "pz"),
            host=os.environ.get("PZ_HOST", "127.0.0.1"),
            port=int(os.environ.get("PZ_PORT", "8177")),
        )
