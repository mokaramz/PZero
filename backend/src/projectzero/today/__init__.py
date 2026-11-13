"""Today (review 030a: the read model): at most 7 human actions, ranked deterministically from existing state.

* ``catalog``: the old constants, cut by script (``scripts/gen_today_catalog.py``);
* ``inputs_model``: ONE frozen ``TodayInputs`` and the pure ``inputs_from_docs`` adapter (old-format documents);
* ``compressor``: the read side of the Triage Queue Compressor (``settings`` / ``summary``), pure;
* ``cases``: the prepared-case rows (``case_prep.summary``) over ``conviction.operator.state_of``, pure;
* ``core``: the old ``services/today.py`` ported line for line (``view``), with the declared decisions (a)-(f).

Nothing here writes, fetches or calls a model.
"""

from projectzero.today.core import view
from projectzero.today.inputs_model import UNREADABLE, TodayInputs, inputs_from_docs

__all__ = ["UNREADABLE", "TodayInputs", "inputs_from_docs", "view"]
