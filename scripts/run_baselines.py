#!/usr/bin/env python3
"""Repository entry point for the prepared-data baseline pilot workflow."""
from pathlib import Path
import sys

sys.dont_write_bytecode=True
package=Path(__file__).resolve().parents[1]/".codex/skills/physicell-modeling/scripts/baselines"
sys.path.insert(0,str(package))
from workflow import main

if __name__=="__main__":
    raise SystemExit(main())
