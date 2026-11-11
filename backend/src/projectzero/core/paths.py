"""Locations inside the repository that code needs at runtime."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACTS_DIR = REPO_ROOT / "contracts"
