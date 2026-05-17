"""LOHI-TRADE CLI — pip install lohi-trade && lohi setup.

This module now enforces a minimum Python version of 3.11.
If the interpreter is older, a clear RuntimeError is raised to prevent obscure import failures.
"""

import sys

if sys.version_info < (3, 11):
    raise RuntimeError(
        "LOHI-TRADE requires Python 3.11 or newer. "
        f"Current interpreter version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )

__version__ = "0.1.0"
