"""Read-only access to the old ``project-zero-data`` folder.

Every file is opened ``rb`` and nothing here can write: the import must never modify its source.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any


class LegacySourceError(RuntimeError):
    pass


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-standard JSON constant {name}")  # NaN/Infinity can't be stored as jsonb


def parse_json_bytes(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)


def parse_jsonl_bytes(raw: bytes) -> list[Any]:
    return [
        json.loads(line, parse_constant=_reject_constant)
        for line in raw.decode("utf-8-sig").splitlines()
        if line.strip()
    ]


@dataclass(frozen=True)
class LegacyFile:
    path: str  # relative, forward slashes
    raw: bytes

    @cached_property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()

    @cached_property
    def parsed(self) -> Any | None:
        """JSON, or JSONL as a list; None for other formats or content Postgres jsonb can't hold."""
        try:
            if self.path.endswith(".json"):
                value = parse_json_bytes(self.raw)
            elif self.path.endswith(".jsonl"):
                value = parse_jsonl_bytes(self.raw)
            else:
                return None
        except (ValueError, UnicodeDecodeError):
            return None
        if "\\u0000" in json.dumps(value):  # jsonb rejects NUL in strings
            return None
        return value


class LegacySource:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        if not self.root.is_dir():
            raise LegacySourceError(f"legacy data folder not found: {self.root}")

    def paths(self) -> list[str]:
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())

    def file(self, path: str) -> LegacyFile:
        full = (self.root / path).resolve()
        if self.root not in full.parents:
            raise LegacySourceError(f"path escapes the legacy folder: {path}")
        with full.open("rb") as handle:
            return LegacyFile(path, handle.read())

    def files(self) -> Iterator[LegacyFile]:
        for path in self.paths():
            yield self.file(path)

    def exists(self, path: str) -> bool:
        return (self.root / path).is_file()

    def json(self, path: str, default: Any = None) -> Any:
        if not self.exists(path):
            return default
        try:
            return parse_json_bytes(self.file(path).raw)
        except ValueError as exc:
            raise LegacySourceError(f"{path}: not valid JSON ({exc})") from exc

    def jsonl(self, path: str) -> list[Any]:
        if not self.exists(path):
            return []
        try:
            return parse_jsonl_bytes(self.file(path).raw)
        except ValueError as exc:
            raise LegacySourceError(f"{path}: not valid JSONL ({exc})") from exc


class LegacySnapshot:
    """Every file of the folder captured once, in memory. Mapping, archive and fingerprint all read these bytes.

    ``capture`` reads the whole folder, then reads it again and compares paths and SHA-256s. If anything changed in
    between (the old app saved a file), it captures again, up to ``attempts`` times, then refuses. The cut-over still
    pauses the old app's scheduler so the folder is quiet; this check proves it was.
    """

    def __init__(self, root: Path, files: dict[str, LegacyFile], attempts: int) -> None:
        self.root = root
        self._files = files
        self.attempts = attempts

    @classmethod
    def capture(
        cls,
        root: Path,
        *,
        attempts: int = 3,
        between_passes: Callable[[int], None] | None = None,
    ) -> LegacySnapshot:
        source = LegacySource(root)
        changed: list[str] = []
        for attempt in range(1, attempts + 1):
            captured = {f.path: f for f in source.files()}
            if between_passes is not None:
                between_passes(attempt)  # test hook: simulates a save during capture
            recheck = {f.path: f.sha256 for f in source.files()}
            changed = sorted(
                (set(captured) ^ set(recheck))
                | {p for p in captured.keys() & recheck.keys() if captured[p].sha256 != recheck[p]}
            )
            if not changed:
                return cls(source.root, captured, attempt)
        raise LegacySourceError(
            f"the legacy folder kept changing during capture ({attempts} attempts); last changes: {changed[:10]}"
        )

    def paths(self) -> list[str]:
        return sorted(self._files)

    def file(self, path: str) -> LegacyFile:
        return self._files[path]

    def files(self) -> Iterator[LegacyFile]:
        for path in self.paths():
            yield self._files[path]

    def exists(self, path: str) -> bool:
        return path in self._files

    def json(self, path: str, default: Any = None) -> Any:
        if path not in self._files:
            return default
        try:
            return parse_json_bytes(self._files[path].raw)
        except ValueError as exc:
            raise LegacySourceError(f"{path}: not valid JSON ({exc})") from exc

    def jsonl(self, path: str) -> list[Any]:
        if path not in self._files:
            return []
        try:
            return parse_jsonl_bytes(self._files[path].raw)
        except ValueError as exc:
            raise LegacySourceError(f"{path}: not valid JSONL ({exc})") from exc
