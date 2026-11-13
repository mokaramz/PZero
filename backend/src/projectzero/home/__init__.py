"""The Investment Desk (review 031a: the read model): the old ``GET /api/home`` over the ported views.

* ``inputs_model``: ONE frozen ``HomeInputs`` and the pure ``inputs_from_docs`` adapter (old-format documents);
* ``core``: the old ``ecosys.home()`` hand-ported line for line (``view``), over ONE Berlin clock (decision b).

Nothing here writes, fetches or calls a model.
"""

from projectzero.home.core import view
from projectzero.home.inputs_model import UNREADABLE, HomeInputs, inputs_from_docs

__all__ = ["UNREADABLE", "HomeInputs", "inputs_from_docs", "view"]
