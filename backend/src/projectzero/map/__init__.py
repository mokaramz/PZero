"""Map (review 025): the pins and the ground-sourcing / ecosystem intelligence.

A mechanical port of the old ``services/geo_intel.py`` and the ``GET /api/map`` pins of ``api/routers/home.py`` (plus
``events.geocode_location`` / ``enrich_signals_with_geo``) at revision 6c739b9. Pure functions over ONE explicit
``MapInputs``; the database adapter loads the inputs, the routes call these. Nothing here writes (decision a).

Modules:

* ``catalog``       constants cut by script (``scripts/gen_map_catalog.py``) from the old modules.
* ``inputs_model``  ``MapInputs`` (frozen; every field documents the old call it replaces, its shape and its ORDER)
  and ``inputs_from_docs(docs, today) -> MapInputs``: the same values from old-format documents ``{path: parsed}``,
  tolerance included (the goldens use it; the database adapter must produce identical values).
* ``network``       ``check_candidates(doc) -> (usable, problems)`` (decision f, revision 2) and ``skip_note``.
* ``pins``          ``map_view(inputs, today) -> dict`` (``GET /api/map/pins``; gains ``new_signals``, decision c).
* ``intel``         ``view(inputs, today, built_at=None) -> dict`` (``GET /api/map/intel``),
  ``detail(inputs, city, today) -> dict`` (``GET /api/map/ecosystem?city=``; ``KeyError`` -> 404),
  ``search(inputs, q, today) -> list`` (``GET /api/map/search?q=``, wrapped as ``{"results": ...}``),
  ``sourcing_day(inputs, city, day, today) -> dict`` (``POST /api/map/sourcing_day``; ``KeyError`` / ``ValueError``
  -> 400), and ``build`` / ``where_to_go`` / ``convergence``.
"""
