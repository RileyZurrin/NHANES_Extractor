"""Legacy entry point for the unified, validated NHANES extraction pipeline."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nhanes_extractor.core import main

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:] or ['run']))
