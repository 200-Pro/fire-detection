"""Prepare local GIS sources without touching the original IMG/ZIP files."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from app.spread.terrain import prepare_data

if __name__ == "__main__":
    import json
    result = prepare_data(root / "runtime" / "external-data", root / "runtime" / "spread-data")
    print(json.dumps(result, ensure_ascii=False, indent=2))
