"""Validation & Learning (review 027a: the read side): is Project Zero finding exceptional companies EARLY?

* ``catalog``: the old constants and vocabularies, cut by script (``scripts/gen_validation_catalog.py``);
* ``inputs_model``: ONE frozen ``ValidationInputs`` and the pure ``inputs_from_docs`` adapter (old-format documents);
  ``candidate_record`` maps a stored candidate row to the record Validation reads (decision f);
* ``core``: the read model ported line for line (``build`` / ``entities``, the metrics, the in-memory daily snapshot,
  ``observations``, ``view``);
* ``routing``: the old ``compressor.metrics``, pure;
* ``packet``: the Scout 00 feedback packet, read only.

Nothing here writes: the four append-only logs, the outcome / audit / retraction / benchmark writes and the packet
``mark`` are review 027b's.
"""

from projectzero.validation.core import ValidationError, build, entities, view
from projectzero.validation.inputs_model import ValidationInputs, candidate_record, inputs_from_docs
from projectzero.validation.packet import scout_packet

__all__ = [
    "ValidationError",
    "ValidationInputs",
    "build",
    "candidate_record",
    "entities",
    "inputs_from_docs",
    "scout_packet",
    "view",
]
