"""News & Learning (review 028a: the read side): external startup / VC news as education, as a BENCHMARK for Project
Zero ("did we know this company before it became news?") and as retrospective learning.

* ``catalog``: the old constants, vocabularies and rules, cut by script (``scripts/gen_news_catalog.py``);
* ``inputs_model``: ONE frozen ``NewsInputs`` and the pure ``inputs_from_docs`` adapter (old-format documents), with
  the request's ONE Validation entity build passed in (decision b);
* ``core``: the read model ported line for line (``classify``, ``materiality``, ``check``, ``backcast_summary``, the
  in-memory ``seed_cases``, ``view``, ``weekly_review``, ``learnings``, ``refresh_status``);
* ``sources``: the pure part of the old ``news_sources`` (``compute``, roles, best uses, bias, missing publications,
  disagreements, ``source_note``, ``scout_lines``, ``view``);
* ``claims``: the ``claims.classify`` slice they read.

Nothing here writes, fetches or calls a model: the outcome / audit / backcast writes are 028b's, the refresh run and
the source evaluation 028c's, the model cards 028d's.
"""

from projectzero.news.core import learnings, refresh_status, seed_cases, view, weekly_review
from projectzero.news.inputs_model import NewsInputs, base_from_docs, inputs_from_docs, with_entities
from projectzero.news.sources import scout_lines
from projectzero.news.sources import view as sources_view

__all__ = [
    "NewsInputs",
    "base_from_docs",
    "inputs_from_docs",
    "learnings",
    "refresh_status",
    "scout_lines",
    "seed_cases",
    "sources_view",
    "view",
    "weekly_review",
    "with_entities",
]
