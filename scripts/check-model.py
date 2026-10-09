"""Read-only model/policy compatibility check. Never auto-register an unvalidated hash."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.config import Settings
from app.detector import YoloDetector
model=YoloDetector(Settings.from_env())
model.load()
if not model.ready:
    raise SystemExit(model.error)
print('Model and policy verified:',model.model_hash)
print('Policy:',model.config['version'],'classes:',model.model.names)
