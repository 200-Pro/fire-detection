from datetime import datetime, timezone
from pathlib import Path
import json
import numpy as np
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models import User
from app.security import hash_password
from app.spread.engine import cellular_automata, geometry_baseline, neighbour_slices
from app.spread.routes import SpreadService, SimulationInput
from app.spread.weather import kma_grid, parse_observation
from app.spread.nifos import parse_danger

WEATHER = {"source": "manual", "temperature_c": 20, "humidity_pct": 30, "wind_speed_ms": 6,
           "wind_from_deg": 270, "rain_mm": 0}


def test_grid_matches_official_seoul_example():
    assert kma_grid(37.5665, 126.9780) == (60, 127)


def test_weather_parsing_freshness_and_direction():
    items = [{"category": k, "obsrValue": str(v), "baseDate": "20261008", "baseTime": "1200"}
             for k, v in {"T1H": 20, "REH": 40, "WSD": 3, "VEC": 270, "RN1": 0}.items()]
    body = {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}}
    result = parse_observation(body, 89, 90, datetime(2026, 10, 8, 3, 50, tzinfo=timezone.utc))
    assert result["available"] and result["fresh"] and result["wind_to_deg"] == 90
    assert result["age_minutes"] == 50
    stale = parse_observation(body, 89, 90, datetime(2026, 10, 8, 6, tzinfo=timezone.utc))
    assert stale["available"] and not stale["fresh"]
    items[0]["obsrValue"] = "nan"
    assert not parse_observation(body, 89, 90)["available"]


def test_weather_error_messages_do_not_echo_provider_text():
    body = {"response": {"header": {"resultCode": "30", "resultMsg": "test-secret-key"}}}
    assert "test-secret" not in json.dumps(parse_observation(body, 1, 1))


def test_ca_reproducible_cumulative_and_no_missing_data_jump():
    elevation = np.zeros((11, 11), "float32")
    fuel = np.ones((11, 11), "float32")
    valid = np.ones((11, 11), bool)
    valid[:, 5] = False
    kwargs = dict(runs=30, seed=42, cell_m=30, ros=15)
    one = cellular_automata(elevation, fuel, valid, (5, 2), WEATHER, [10, 30], **kwargs)
    two = cellular_automata(elevation, fuel, valid, (5, 2), WEATHER, [10, 30], **kwargs)
    assert np.array_equal(one[30], two[30])
    assert (one[30] >= one[10]).all()
    assert not one[30][:, 5:].any()
    assert one[30][5, 2] == 1
    assert (one[30] >= 0).all() and (one[30] <= 1).all()


def test_neighbour_slice_has_no_opposite_edge_wrap():
    source, destination = neighbour_slices(5, 5, 1, 1)
    assert source == (slice(0, 4), slice(0, 4))
    assert destination == (slice(1, 5), slice(1, 5))


def test_west_wind_pushes_ellipse_east():
    valid = np.ones((21, 21), bool)
    output = geometry_baseline(valid, (10, 10), WEATHER, [30], cell_m=30, ros=6, ellipse=True)[30]
    rr, cc = np.indices(valid.shape)
    assert float((output * cc).sum() / output.sum()) > 10
    assert abs(float((output * rr).sum() / output.sum()) - 10) < .01


def test_api_requires_auth_confirmation_and_real_weather(tmp_path, monkeypatch):
    class Detector:
        ready = True
        error = None
        info = {"ready": True}
        def load(self): pass
    # A genuine prepared-data manifest can be reused read-only; jobs stay isolated.
    data_dir = Path(__file__).resolve().parents[2] / "runtime" / "spread-data"
    if not (data_dir / "manifest.json").is_file():
        pytest.skip("Local GIS fixture absent")
    cfg = Settings(environment="testing", database_url=f"sqlite:///{tmp_path}/test.db",
        storage_path=tmp_path / "evidence", spread_data_path=data_dir, spread_jobs_path=tmp_path / "jobs")
    app = create_app(cfg, Detector())
    with TestClient(app) as client:
        client.headers["X-Ember-Client"] = "web"
        assert client.get("/spread/status").status_code == 404
        assert client.get("/api/spread/status").status_code == 401
        assert client.get("/api/fire-danger").status_code == 401
        assert client.post("/api/auth/login", json={"username": "admin", "password": "fire-demo-local"}).status_code == 200
        status = client.get("/api/spread/status").json()
        assert status["ready"]
        point = status["manifest"]["default_ignition"]
        payload = {**point, "weather_mode": "manual", "manual_weather": WEATHER}
        assert client.post("/api/simulations", json=payload).status_code == 422
        payload["location_confirmed"] = True
        payload["latitude"] = 38
        assert client.post("/api/simulations", json=payload).status_code == 422
        payload.update(point)
        monkeypatch.setenv("KMA_SERVICE_KEY", "")
        payload["weather_mode"] = "kma"
        assert client.post("/api/simulations", json=payload).status_code == 503
        assert app.state.spread.inflight == 0
        payload["weather_mode"] = "manual"
        payload["event_id"] = "a" * 32
        assert client.post("/api/simulations", json=payload).status_code == 404
        # Public job API must not reveal other users' inputs or results.
        service = app.state.spread
        job = {"id": "a" * 32, "state": "completed", "owner_id": "other-owner", "created_at": "2026"}
        service.write_job(job)
        assert client.get("/api/simulations/" + "a" * 32).status_code == 404
        assert client.get("/api/simulations/" + "a" * 32 + "/perimeters").status_code == 404
        assert not client.get("/api/simulations").json()["items"]
        assert client.get("/api/simulations/../manifest").status_code == 404
        monkeypatch.setenv('NIFOS_SERVICE_KEY', '')
        assert not client.get('/api/fire-danger').json()['available']


def test_restarting_marks_abandoned_job_failed(tmp_path):
    service = SpreadService(tmp_path / "data", tmp_path / "jobs")
    service.write_job({"id": "b" * 32, "owner_id": "owner", "state": "running"})
    service.startup()
    assert service.get_job("b" * 32, "owner")["state"] == "failed"


def test_failed_job_persistence_still_releases_queue_capacity(tmp_path, monkeypatch):
    import asyncio
    service = SpreadService(tmp_path / 'data', tmp_path / 'jobs')
    service.inflight = 1
    def full_disk(_):
        raise OSError('synthetic disk full')
    monkeypatch.setattr(service, 'write_job', full_disk)
    with pytest.raises(OSError):
        asyncio.run(service.calculate({'id': 'd' * 32, 'request': {}}))
    assert service.inflight == 0


def test_input_limits_reject_nan_and_excessive_runs():
    from pydantic import ValidationError
    for changes in ({"latitude": float("nan")}, {"runs": 10000}, {"horizon_min": 120}):
        with pytest.raises(ValidationError):
            SimulationInput(**({"latitude": 35.8, "longitude": 128.6} | changes))


def test_changed_grid_is_rejected_before_computation(tmp_path):
    from app.spread.engine import run_simulation
    (tmp_path / 'manifest.json').write_text(json.dumps({'grid_sha256': '0' * 64}), encoding='utf-8')
    (tmp_path / 'grid.npz').write_bytes(b'changed-data')
    with pytest.raises(ValueError, match='해시'):
        run_simulation({}, str(tmp_path))


def test_nifos_separates_future_forecast_from_latest_past_time():
    items = [{'regioncode': 27, 'analdate': f'2026-10-08 {hour}', 'mini': 4, 'meanavg': 24, 'maxi': 52}
             for hour in ('08', '12')]
    body = {'response': {'header': {'resultCode': '00'}, 'body': {'items': {'item': items}}}}
    result = parse_danger(body, datetime(2026, 10, 8, 0, 30, tzinfo=timezone.utc))
    assert result['available'] and result['fresh']
    assert result['current']['valid_at'] == '2026-10-07T23:00:00+00:00'
    assert len(result['forecasts']) == 1 and result['forecasts'][0]['future_time']
    stale = parse_danger(body, datetime(2026, 10, 9, 0, tzinfo=timezone.utc))
    assert not stale['fresh']


def test_nifos_rejects_other_regions_invalid_values_and_secret_messages():
    body = {'response': {'header': {'resultCode': '30', 'resultMsg': 'example-secret-key'}}}
    assert 'example-secret' not in json.dumps(parse_danger(body))
    body['response'] = {'header': {'resultCode': '00'}, 'body': {'items': {'item': {
        'regioncode': 11, 'analdate': '2026-10-08 08', 'mini': 4, 'meanavg': 24, 'maxi': 52}}}}
    assert not parse_danger(body)['available']
    body['response']['body']['items']['item'].update(regioncode=27, meanavg=float('nan'))
    assert not parse_danger(body)['available']
