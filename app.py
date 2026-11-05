"""
app.py — Pocket Agent launcher.

Windows: double-click start.bat (after running setup.bat once).
Or from a terminal:  python app.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import main

if __name__ == "__main__":
    main()
