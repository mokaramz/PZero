"""Operator tools: the importer, the preview, the parity checks.

None of them serves the app, but many build it (``create_app``) over a throw-away schema, and the app's start runs the
overdue background jobs (032c), which fetch the network. So importing ``ops`` turns that catch-up OFF for the process
(review 034a). ``parity_jobs`` sets it on explicitly, and restores it, where it tests the catch-up itself.
"""

import os

os.environ["PZ_CATCHUP"] = "0"
