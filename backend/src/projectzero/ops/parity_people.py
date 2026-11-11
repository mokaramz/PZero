"""Person-key parity: ``network.identity.fold`` against the OLD ``services/identity.fold`` (review 012).

    python -m projectzero.ops.parity_people goldens   # (re)generate golden_v1/oracle_people_fold.json
    python -m projectzero.ops.parity_people real      # every name in the real people.json (counts only, nothing kept)

The oracle (``scripts/oracle/people_fold_oracle.py``) runs the old function in the old interpreter with a scratch
``PZ_DATA``. ``real`` reads the legacy folder through the read-only snapshot and prints only counts and positions.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from projectzero.network.identity import fold
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO

ORACLE = Path(__file__).resolve().parents[4] / "scripts" / "oracle" / "people_fold_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_people_fold.json"


def corpus() -> list[Any]:
    """Synthetic names that walk every branch of the old key: titles, ß / ẞ, accents, scripts, punctuation, types."""
    return [
        "Ada Lovelace", "  ada   LOVELACE  ", "Jürgen Groß", "JÜRGEN GROẞ", "Straße", "Müller-Lüdenscheidt",
        "Dr. Ada Lovelace", "Dr Ada Lovelace", "dr. ada lovelace", "Prof. Dr. Jürgen Groß", "Prof Dr Hans Meier",
        "Prof. Dr.-Ing. Hans Meier", "Dr.-Ing. Anna Schmidt", "Dr.-ing Anna Schmidt", "Dipl.-Ing. Lena Weiß",
        "Dipl. Ing. Lena Weiß", "Mag. Eva Bauer", "MBA Jane Roe", "PhD Jane Roe", "phd. jane roe",
        "Jane Roe, PhD", "Jane Roe PhD", "Jane Roe (Dr.)", "Dr.Ada Lovelace", "Drake Bell", "Ingrid Ing",
        "Mba Diallo", "Prof.", "Dr. ", "Dr. Dr. Ada", "Prof. Prof. Dr. Ada", "Dr. med. Ada Lovelace",
        "Ada Dr. Lovelace", "Hans Prof Meier", "Alexandr Ivanov", "Sing Song", "Ada Lovelace phd",
        "Ayşe Y\u0131ld\u0131z Kaya", "João Brás da Costa", "Søren Kierkegaard", "Łukasz Żółć", "Đorđe Novak",
        "Æsa Ødegaard", "\ufb01ona Ligature", "\uff26\uff55\uff4c\uff4c \uff37\uff49\uff44\uff54\uff48",
        "José\u00a0María", "Zoë\tO'Brien",
        "Jean-Luc Picard", "O'Neil", "Ada Lovelace 3rd", "R2-D2", "Ada_Lovelace", "ada.lovelace@example.com",
        "@adalove", "李小龙", "Владимир Путинцев", "محمد كرم", "Μαρία Κάλλας", "", " ", "-", "?", "UNKNOWN",
        None, 0, 1, 42, 3.5, True, False, ["Ada"], {"name": "Ada"},
    ]  # fmt: skip


def run_oracle(values: list[Any]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-fold-oracle-") as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "data").mkdir()
        src, dst = tmpdir / "in.json", tmpdir / "out.json"
        src.write_text(json.dumps({"values": values}, ensure_ascii=False), encoding="utf-8")
        env = {**os.environ, "PZ_DATA": str(tmpdir / "data"), "PYTHONPATH": str(OLD_REPO / "backend" / "src")}
        env.pop("SUPABASE_DB_URL", None)
        run = subprocess.run([str(python), str(ORACLE), str(src), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


def mismatches(values: list[Any], expected: list[str]) -> list[int]:
    return [i for i, (v, e) in enumerate(zip(values, expected, strict=True)) if fold(v) != e]


def write_goldens() -> int:
    values = corpus()
    oracle = run_oracle(values)
    cases = [{"value": v, "folded": f} for v, f in zip(values, oracle["folded"], strict=True)]
    GOLDEN.write_text(
        json.dumps({"provenance": oracle["meta"], "cases": cases}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    bad = mismatches(values, oracle["folded"])
    print(f"people-fold goldens written: {len(cases)} cases; new code differences: {len(bad)} {bad[:20]}")
    return 1 if bad else 0


def real() -> int:
    from projectzero.core.config import load_dotenv
    from projectzero.ops.legacy.convert import records
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    names = [p.get("name") for p in records((snapshot.json("people.json", {}) or {}).get("people"))]
    oracle = run_oracle(names)
    bad = mismatches(names, oracle["folded"])
    print(json.dumps({"names": len(names), "differences": len(bad), "positions": bad[:20], "oracle": oracle["meta"]}))
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    if argv[1:] == ["real"]:
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
