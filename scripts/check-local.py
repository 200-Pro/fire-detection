"""Offline new-PC preflight; never prints credentials or requests public video."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-spread', action='store_true')
    parser.add_argument('--require-utic', action='store_true')
    args = parser.parse_args()
    checks = []

    def record(name, ok, required=True):
        checks.append({'check': name, 'status': 'ok' if ok else ('error' if required else 'optional_missing')})

    record('python_3_12', sys.version_info[:2] == (3, 12))
    record('local_env_file', (ROOT / '.env').is_file())
    record('frontend_dependencies', (ROOT / 'frontend/node_modules/vite/bin/vite.js').is_file())
    node = shutil.which('node')
    try:
        version = subprocess.check_output([node, '--version'], text=True, timeout=10).strip().lstrip('v') if node else ''
        major, minor, patch = map(int, version.split('.'))
        supported = (major == 20 and (minor, patch) >= (19, 0)) or (major, minor, patch) >= (22, 12, 0)
    except (ValueError, OSError, subprocess.SubprocessError):
        supported = False
    record('node_vite_supported_version', supported)
    try:
        from app.config import Settings
        from app.detector import YoloDetector
        cfg = Settings.from_env()
        model = YoloDetector(cfg)
        model.load()
        record('model_policy_sha_and_classes', model.ready)
        record('demo_samples_or_demo_disabled', not cfg.demo_enabled or all(
            (cfg.samples_path / name).is_file() for name in ('fire.jpg', 'clear.jpg')))
        record('unique_initial_password', cfg.admin_password != 'fire-demo-local', required=False)
        spread = cfg.spread_data_path
        try:
            manifest = json.loads((spread / 'manifest.json').read_text(encoding='utf-8'))
            complete = all((spread / name).is_file() for name in ('grid.npz', 'forest.geojson', 'terrain.geojson'))
            complete = complete and hashlib.sha256((spread / 'grid.npz').read_bytes()).hexdigest() == manifest['grid_sha256']
        except (OSError, ValueError, KeyError):
            complete = False
        record('spread_bundle_and_grid_hash', complete, required=args.require_spread)
        utic_path = Path(os.getenv('UTIC_CATALOG_PATH', str(ROOT / 'runtime/external-data/cctv/OpenDataCCTV.xlsx')))
        try:
            from app.utic import read_catalog
            utic_ready = bool(read_catalog(utic_path)[0])
        except Exception:
            utic_ready = False
        record('utic_local_catalog', utic_ready, required=args.require_utic)
        for name in ('KMA_SERVICE_KEY', 'NIFOS_SERVICE_KEY', 'NAVER_MAPS_CLIENT_ID',
                     'NAVER_MAPS_CLIENT_SECRET', 'ITS_API_KEY', 'UTIC_API_KEY'):
            record(name + '_configured', bool(os.getenv(name, '').strip()), required=args.require_utic and name == 'UTIC_API_KEY')
    except Exception:
        # Config exceptions can contain an invalid env value: never echo them.
        record('dependencies_and_configuration_load', False)
    ok = not any(c['status'] == 'error' for c in checks)
    print(json.dumps({'ready_for_local_start': ok, 'checks': checks,
                      'network_verified': False, 'fresh_machine_install_verified': False}, ensure_ascii=True, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
