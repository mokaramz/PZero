"""Founder Radar (review 026a): the pure domain of ``/founder-radar``, ported from the old
``domain/founder_radar/`` and ``api/routers/founder_radar.py`` (rev 6c739b9). ``routes`` holds the endpoints as pure
functions over the stored documents; ``catalog`` the constants cut by script. No I/O here (``store`` is the database
adapter and is not imported by this package)."""
