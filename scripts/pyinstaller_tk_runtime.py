"""Point bundled Tk 9 at the Tcl/Tk libraries unpacked during the build."""

import os
import sys
from pathlib import Path


bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
for variable, directory in (("TCL_LIBRARY", "tcl_library"), ("TK_LIBRARY", "tk_library")):
    candidate = bundle / directory
    if candidate.is_dir():
        os.environ[variable] = str(candidate)
