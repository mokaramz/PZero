"""A preview database for UI checks: the real snapshot imported into a SCRATCH schema (never the live ``pz``).

    python -m projectzero.ops.preview create     # prints the schema name (pz_rehearse_<hex>)
    PZ_SCHEMA=<name> python -m projectzero.api    # serve it
    python -m projectzero.ops.preview drop <name>
    scripts/db.ps1 cleanup                        # also drops any leftover scratch schema

Decisions clicked in the preview write only to that scratch schema.
"""

from __future__ import annotations

import os
import re
import secrets
import sys
from pathlib import Path

from psycopg import sql

from projectzero.core.config import Settings, load_dotenv
from projectzero.core.db import connect
from projectzero.ops.db_check import SCRATCH_PATTERN, _scratch_sql


def create() -> str:
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    schema = f"pz_rehearse_{secrets.token_hex(4)}"
    with connect(settings.db_url, autocommit=True) as admin:
        admin.execute(_scratch_sql(schema).encode())
    conn = connect(settings.db_url)
    try:
        applied = apply_plan(build_plan(snapshot), schema=schema, conn=conn)
        assert applied.get("applied"), applied
    finally:
        conn.close()
    return schema


def drop(schema: str) -> None:
    if not re.match(SCRATCH_PATTERN, schema):
        raise SystemExit(f"refusing to drop {schema!r}: not a scratch schema")
    load_dotenv()
    with connect(Settings.from_env().db_url, autocommit=True) as admin:
        admin.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(schema)))


def main(argv: list[str]) -> int:
    if argv[1:] == ["create"]:
        print(create())
        return 0
    if argv[1:2] == ["drop"] and len(argv) == 3:
        drop(argv[2])
        print("dropped", argv[2])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
