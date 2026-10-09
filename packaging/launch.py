"""Entry point for the packaged app (PyInstaller needs a script, not `-m`)."""

import multiprocessing
import sys

# Must run before anything else so the format helper process doesn't open a second window.
multiprocessing.freeze_support()

from ndi_multiviewer.__main__ import main  # noqa: E402

sys.exit(main())
