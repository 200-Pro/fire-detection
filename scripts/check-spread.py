"""Read-only GIS/engine checks; optional generated verification report, no API key."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.spread.engine import run_simulation
from app.spread.terrain import digest_file, load_manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    data = ROOT / 'runtime' / 'spread-data'
    sources = ROOT / 'runtime' / 'external-data'
    manifest = load_manifest(data)
    source_checks = []
    for source in manifest['sources']:
        candidates = [p for p in sources.rglob(source['name']) if p.is_file()]
        unchanged = bool(candidates) and all(digest_file(p) == source['sha256'] for p in candidates)
        source_checks.append({'name': source['name'], 'unchanged': unchanged})
        assert unchanged, 'Source changed or missing: ' + source['name']
    assert digest_file(data / 'grid.npz') == manifest['grid_sha256']
    weather = {'source': 'manual', 'temperature_c': 20, 'humidity_pct': 40,
               'wind_speed_ms': 3, 'wind_from_deg': 270, 'rain_mm': 0}
    request = {**manifest['default_ignition'], 'model': 'ca', 'horizon_min': 30,
               'runs': 30, 'seed': 42, 'base_ros_m_min': 6, 'weather': weather}
    cases, results = [], {}
    for name, changes in [('ca', {}), ('repeat', {}), ('circle', {'model': 'circle'}),
                           ('ellipse', {'model': 'ellipse'}),
                           ('wind_calm', {'weather': {**weather, 'wind_speed_ms': 0}}),
                           ('wind_6', {'weather': {**weather, 'wind_speed_ms': 6}}),
                           ('humidity_20', {'weather': {**weather, 'humidity_pct': 20}}),
                           ('humidity_80', {'weather': {**weather, 'humidity_pct': 80}}),
                           ('rain_5', {'weather': {**weather, 'rain_mm': 5}}),
                           ('wind_from_90', {'weather': {**weather, 'wind_from_deg': 90}}),
                           ('horizon_60', {'horizon_min': 60}),
                           ('dry_windy', {'weather': {**weather, 'humidity_pct': 20, 'wind_speed_ms': 6}}),
                           ('humid_rain', {'weather': {**weather, 'humidity_pct': 80, 'rain_mm': 5}})]:
        result = run_simulation(request | changes, str(data))
        results[name] = result
        geom_hash = hashlib.sha256(json.dumps(result['features'], sort_keys=True).encode()).hexdigest()
        cases.append({'case': name, 'request': request | changes, 'geometry_sha256': geom_hash,
                      'horizons': result['summary']['horizons'], 'runtime_ms': result['summary']['runtime_ms']})
    assert cases[0]['geometry_sha256'] == cases[1]['geometry_sha256'], 'Repeatability failed'
    for name in ('wind_calm','wind_6','humidity_20','humidity_80','rain_5','wind_from_90'):
        assert results[name]['features'] != results['ca']['features'], 'Single-factor sensitivity failed: ' + name
    assert all(result['summary']['horizons'][0]['mean_area_ha'] <= result['summary']['horizons'][-1]['mean_area_ha']
               for result in results.values())
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'source_checks': source_checks,
              'grid_sha256': manifest['grid_sha256'], 'engine_sha256': results['ca']['summary']['engine_sha256'],
              'repeatability': True, 'weather_sensitivity': True, 'single_factor_sensitivity': True, 'cumulative_area': True,
              'cases': cases, 'accuracy_validated': False,
              'warning': '소프트웨어 동작 검증만 수행했습니다. 실제 산불 확산 정확도 검증이 아닙니다.'}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
