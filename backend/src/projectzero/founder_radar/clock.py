"""The one request clock of Founder Radar (decision g of review 026a): every timestamp and window is the Berlin wall
clock of the request. ``now`` is a Berlin wall clock (aware Europe/Berlin, or naive = already Berlin wall time, as in
the old app); ``today`` is its day. The old code read ``datetime.now()`` / ``date.today()`` (machine-local)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from projectzero.network.view import berlin_now


@dataclass(frozen=True)
class Clock:
    now: datetime
    today: date

    @classmethod
    def at(cls, now: datetime, today: date | None = None) -> Clock:
        wall = berlin_now(now)
        return cls(wall, today if today is not None else wall.date())

    def minute(self) -> str:
        """``datetime.now().strftime("%Y-%m-%d %H:%M")``"""
        return self.now.strftime("%Y-%m-%d %H:%M")

    def second(self) -> str:
        """``datetime.now().strftime("%Y-%m-%d %H:%M:%S")``"""
        return self.now.strftime("%Y-%m-%d %H:%M:%S")

    def day(self) -> str:
        """``date.today().isoformat()``"""
        return self.today.isoformat()
