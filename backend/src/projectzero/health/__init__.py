"""System health (review 032a): the read side of the old ``GET /api/system_health`` and ``GET
/api/system_health_overview`` as pure functions of ONE frozen ``HealthInputs`` (``core``), the constants and pure
rules cut by script from the old modules (``catalog``), and the old-format adapter the goldens use
(``inputs_model.inputs_from_docs``). The database reader is ``health/inputs.py`` (not part of this package's pure
side)."""

from projectzero.conviction.inputs import UNREADABLE
from projectzero.health.core import RUNNER, Runner, overview_view, system_view
from projectzero.health.inputs_model import HealthInputs, inputs_from_docs

__all__ = ["RUNNER", "UNREADABLE", "HealthInputs", "Runner", "inputs_from_docs", "overview_view", "system_view"]
