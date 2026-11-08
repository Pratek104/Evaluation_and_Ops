"""Primary Streamlit entrypoint for the XYZ employee portal."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from xyz_portal.ui.app import run  # noqa: E402

run()
