"""Bounded, reproducible CA and geometry baselines, with uncalibrated model time."""
from math import atan2, cos, pi, hypot
from pathlib import Path
import time
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.transform import Affine
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform as transform_geometry
from .terrain import load_manifest, digest_file

ENGINE_VERSION = "research-ca-v1.2-provenance"


def neighbour_slices(rows, cols, dr, dc):
    """Source to destination slices, never wrap opposite map edges."""
    source = (slice(max(0, -dr), rows - max(0, dr)), slice(max(0, -dc), cols - max(0, dc)))
    destination = (slice(max(0, dr), rows - max(0, -dr)), slice(max(0, dc), cols - max(0, -dc)))
    return source, destination


def cellular_automata(elevation, fuel, valid, ignition, weather, horizons, runs=30, seed=42, cell_m=90, ros=6):
    """Monte Carlo frequencies conditional on hypotheses; not real-world probabilities."""
    rng = np.random.default_rng(seed)
    rows, cols = valid.shape
    age = np.full((runs, rows, cols), -1, dtype="int16")
    age[:, ignition[0], ignition[1]] = 0
    outputs = {}
    dt = 1 / 3  # Model minutes, twenty seconds per iteration.
    duration_steps = 24  # Uncalibrated eight-minute cell burn duration.
    moisture = np.clip(1.20 - .008 * weather["humidity_pct"], .35, 1.2)
    moisture *= np.exp(-min(weather["rain_mm"], 10) * .35)
    wind_to = (weather["wind_from_deg"] + 180) % 360
    transitions = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == dc == 0:
                continue
            source, destination = neighbour_slices(rows, cols, dr, dc)
            distance = cell_m * hypot(dr, dc)
            angle = atan2(dc, -dr) * 180 / pi % 360
            wind_factor = np.exp(np.clip(.13 * weather["wind_speed_ms"] * cos((angle - wind_to) * pi / 180), -2, 2))
            slope = np.clip((elevation[destination] - elevation[source]) / distance, -.7, .7)
            hazard = ros * fuel[destination] * moisture * wind_factor * np.exp(2.5 * slope) / distance
            probability = np.clip(1 - np.exp(-hazard * dt), 0, .70)
            probability = np.where(valid[source] & valid[destination], probability, 0)
            transitions.append((source, destination, probability))
    checkpoints = {int(round(h / dt)): h for h in horizons}
    for step in range(1, max(checkpoints) + 1):
        active = (age >= 0) & (age < duration_steps)
        survival = np.ones(age.shape, dtype="float32")
        for source, destination, probability in transitions:
            survival[(slice(None),) + destination] *= 1 - active[(slice(None),) + source] * probability
        ignite = (age < 0) & valid[None, ...] & (rng.random(age.shape) < (1 - survival))
        age[age >= 0] += 1
        age[ignite] = 0
        if step in checkpoints:
            outputs[checkpoints[step]] = (age >= 0).mean(axis=0).astype("float32")
    return outputs


def geometry_baseline(valid, ignition, weather, horizons, cell_m=90, ros=6, ellipse=False):
    rr, cc = np.indices(valid.shape)
    east = (cc - ignition[1]) * cell_m
    north = (ignition[0] - rr) * cell_m
    wind_to = (weather["wind_from_deg"] + 180) * pi / 180
    downwind = east * np.sin(wind_to) + north * np.cos(wind_to)
    crosswind = east * np.cos(wind_to) - north * np.sin(wind_to)
    outputs = {}
    ratio = 1 + min(weather["wind_speed_ms"], 15) * .18 if ellipse else 1
    for minute in horizons:
        radius = max(ros * minute, cell_m / 2)
        shift = radius * (ratio - 1) * .5
        burn = ((downwind - shift) / (radius * ratio)) ** 2 + (crosswind / radius) ** 2 <= 1
        burn[ignition] = True
        outputs[minute] = (burn & valid).astype("float32")
    return outputs


def run_simulation(request: dict, data_dir: str):
    started = time.perf_counter()
    data_dir = Path(data_dir)
    manifest = load_manifest(data_dir)
    if digest_file(data_dir / "grid.npz") != manifest.get("grid_sha256"):
        raise ValueError("전처리 격자의 해시가 다릅니다. 지도를 다시 전처리하세요.")
    affine = Affine(*manifest["transform"])
    project = Transformer.from_crs(4326, manifest["crs"], always_xy=True)
    geographic = Transformer.from_crs(manifest["crs"], 4326, always_xy=True)
    x, y = project.transform(request["longitude"], request["latitude"])
    column, row = (~affine) * (x, y)
    row, column = int(np.floor(row)), int(np.floor(column))
    with np.load(data_dir / "grid.npz", allow_pickle=False) as data:
        elevation, fuel, valid = data["elevation"], data["fuel"], data["valid"]
    if not (0 <= row < valid.shape[0] and 0 <= column < valid.shape[1]) or not valid[row, column]:
        raise ValueError("발화점이 사용 가능한 숲 격자 밖입니다. 초록색 숲 내부를 선택하세요.")
    # Limit processing to a 5 km window around ignition. Boundary contact is reported.
    radius = int(np.ceil(2500 / manifest["grid_m"]))
    top, left = max(0, row - radius), max(0, column - radius)
    bottom, right = min(valid.shape[0], row + radius + 1), min(valid.shape[1], column + radius + 1)
    elevation, fuel, valid = [a[top:bottom, left:right] for a in (elevation, fuel, valid)]
    ignition = row - top, column - left
    window_transform = affine * Affine.translation(left, top)
    weather = request["weather"]
    horizons = sorted(set([h for h in (10, 30, 60) if h <= request["horizon_min"]] + [request["horizon_min"]]))
    kwargs = dict(cell_m=manifest["grid_m"], ros=request["base_ros_m_min"])
    if request["model"] == "ca":
        outputs = cellular_automata(elevation, fuel, valid, ignition, weather, horizons,
                                    request["runs"], request["seed"], **kwargs)
        repeats = request["runs"]
    else:
        outputs = geometry_baseline(valid, ignition, weather, horizons, ellipse=request["model"] == "ellipse", **kwargs)
        repeats = 1
    features, summaries = [], []
    touches_boundary = False
    for minute, frequency in outputs.items():
        contacted = (frequency[0, :].any() or frequency[-1, :].any() or frequency[:, 0].any() or frequency[:, -1].any())
        touches_boundary = touches_boundary or bool(contacted)
        summaries.append({"minute": minute, "mean_area_ha": round(float(frequency.sum()) * manifest["grid_m"] ** 2 / 10000, 2),
                          "any_run_area_ha": round(int((frequency > 0).sum()) * manifest["grid_m"] ** 2 / 10000, 2)})
        for threshold in ([.1, .5, .9] if request["model"] == "ca" else [1.0]):
            mask = (frequency >= threshold).astype("uint8")
            for geom, value in shapes(mask, mask=mask.astype(bool), transform=window_transform):
                geographic_shape = transform_geometry(geographic.transform, shape(geom))
                features.append({"type": "Feature", "geometry": mapping(geographic_shape), "properties": {
                    "minute": minute, "frequency_threshold": threshold, "model": request["model"],
                    "label": "조건부 시뮬레이션 반복 비율, 실제 화재 확률 아님"}})
    warnings = list(manifest["warnings"]) + [
        "표시 시간은 보정되지 않은 모델 시간입니다. 실제 도달시각·대피 판단에 사용하지 마세요.",
        "수관화·비화·진압·산악 미기상은 반영되지 않습니다.",
        "선택한 기상 조건을 전체 계산 동안 고정합니다. 시간에 따른 기상 변화는 반영하지 않습니다.",
        ("발화점은 보정 영상의 불꽃 지면 접점 근사입니다. 최초 발화점·실측 좌표가 아니며 위치 오차를 별도로 확인하세요."
         if request.get("location_source")=="automatic_calibrated_estimate" else
         "발화점은 사용자가 지정한 가상 지점입니다. 영상에서 추정한 실제 좌표가 아닙니다.")]
    if weather.get("source") == "manual":
        warnings.append("수동으로 입력한 가상 기상 조건입니다. 실시간 관측값이 아닙니다.")
    if touches_boundary:
        warnings.append("결과가 계산 창 경계에 닿았습니다. 창 밖으로 확산이 이어질 수 있습니다.")
    return {"type": "FeatureCollection", "features": features,
        "summary": {"horizons": summaries, "grid_m": manifest["grid_m"], "runs": repeats,
            "seed": request["seed"], "engine_version": ENGINE_VERSION, "data_sha256": manifest["data_sha256"],
            "grid_sha256": manifest.get("grid_sha256"),
            "engine_sha256": digest_file(Path(__file__)),
            "parameters": {"base_ros_m_min": request["base_ros_m_min"],
                "ca_dt_model_min": 1 / 3, "ca_burn_duration_model_min": 8,
                "fuel_mapping": manifest["fuel_mapping"], "weather_constant": True},
            "software": {"numpy": np.__version__, "rasterio": rasterio.__version__},
            "runtime_ms": round((time.perf_counter() - started) * 1000), "boundary_contact": touches_boundary,
            "valid_forest_cells": int(valid.sum()), "calibrated": False, "warnings": warnings}}
