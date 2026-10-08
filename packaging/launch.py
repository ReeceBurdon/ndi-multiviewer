"""Entry point for the packaged app (PyInstaller needs a script, not `-m`)."""

import sys

from ndi_multiviewer.__main__ import main

sys.exit(main())
