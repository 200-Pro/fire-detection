"""Read-only source ingestion; generated products live in runtime/spread-data."""
from io import BytesIO
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import zipfile
import numpy as np
import rasterio
from rasterio.features import rasterize, shapes
from pyproj import CRS, Transformer
import shapefile
from shapely.geometry import shape, mapping
from shapely.ops import transform as transform_geometry

def read_dem_tiles(paths):
    """Mosaic aligned meter grids; no resampling disguised as added resolution."""
    if not paths or len(paths)>16:
        raise ValueError("DEM 타일은 1~16개가 필요합니다.")
    from rasterio.merge import merge
    with ExitStack() as stack:
        datasets=[stack.enter_context(rasterio.open(path)) for path in paths]
        first=datasets[0];crs=CRS.from_user_input(first.crs);affine=first.transform
        resolution=abs(affine.a)
        if affine.b or affine.d or affine.a<=0 or affine.e>=0 or not crs.is_projected:
            raise ValueError("미터 단위 북향 DEM이 필요합니다.")
        if not np.isclose(abs(affine.e),resolution) or not crs.axis_info or crs.axis_info[0].unit_name!="metre":
            raise ValueError("미터 단위 정사각 격자가 필요합니다.")
        for src in datasets:
            a=src.transform
            if (src.crs!=first.crs or a.b or a.d or not np.isclose(a.a,resolution)
                or not np.isclose(a.e,-resolution)):
                raise ValueError("동일 좌표계·해상도·북향 DEM 타일만 결합합니다.")
            offsets=[(a.c-affine.c)/resolution,(a.f-affine.f)/resolution]
            if any(not np.isclose(v,round(v)) for v in offsets):
                raise ValueError("DEM 타일 격자의 원점이 정렬되지 않았습니다.")
        west=min(d.bounds.left for d in datasets);east=max(d.bounds.right for d in datasets)
        south=min(d.bounds.bottom for d in datasets);north=max(d.bounds.top for d in datasets)
        if (east-west)*(north-south)/resolution**2>4_000_000:
            raise ValueError("로컬 DEM 결합 격자 한도를 초과합니다.")
        if len(datasets)==1:
            elevation=first.read(1,masked=True).filled(np.nan).astype("float32")
        else:
            mosaic,affine=merge(datasets,nodata=np.nan,dtype="float32",indexes=[1])
            elevation=mosaic[0]
        return elevation,crs,affine,resolution,(west,south,east,north)


def digest_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collection(features):
    return {"type": "FeatureCollection", "features": features}


def prepare_data(source_root: Path, output: Path):
    dem_files = sorted(p for p in (source_root/"terrain"/"raw").rglob("*")
                       if p.is_file() and p.suffix.lower() in (".img",".tif",".tiff"))
    if not dem_files:
        raise ValueError("DEM .img 파일이 없습니다.")
    forest_files = sorted((source_root / "forest").rglob("*임상도.zip"))
    soil_files = sorted(source_root.rglob("*토양도.zip"))
    if not forest_files:
        raise ValueError("이름에 임상도가 포함된 ZIP이 필요합니다.")
    output.mkdir(parents=True, exist_ok=True)
    elevation,crs,affine,resolution,bounds=read_dem_tiles(dem_files)
    to_geo = Transformer.from_crs(crs, 4326, always_xy=True)
    sources = [{"name": p.name, "sha256": digest_file(p), "kind": "dem"} for p in dem_files]
    features, forest_shapes, soil_shapes, years = [], [], [], set()
    factors = {"1": 1.20, "2": .90, "3": 1.05}  # Hypotheses, NOT calibrated fuel models.
    forest_count = soil_count = 0
    for kind, files in (("forest", forest_files), ("soil", soil_files)):
        for path in files:
            sources.append({"name": path.name, "sha256": digest_file(path), "kind": kind})
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:
                    raise ValueError(f"압축파일 손상: {path.name}")
                names = {Path(n).suffix.lower(): n for n in archive.namelist() if not n.endswith("/")}
                if not {".shp", ".dbf", ".prj"} <= names.keys():
                    raise ValueError(f"SHP/DBF/PRJ 누락: {path.name}")
                source_crs = CRS.from_wkt(archive.read(names[".prj"]).decode("utf-8-sig"))
                project = Transformer.from_crs(source_crs, crs, always_xy=True).transform
                reader = shapefile.Reader(shp=BytesIO(archive.read(names[".shp"])),
                                          dbf=BytesIO(archive.read(names[".dbf"])), encoding="cp949")
                for record in reader.iterShapeRecords():
                    attrs = record.record.as_dict()
                    geom = transform_geometry(project, shape(record.shape.__geo_interface__))
                    if not geom.is_valid:
                        geom = geom.buffer(0)
                    if geom.is_empty:
                        continue
                    if kind == "soil":
                        soil_count += 1
                        soil_shapes.append((mapping(geom), soil_count))
                        continue  # Soil codes are not live moisture or calibrated fuel.
                    forest_count += 1
                    code = str(attrs.get("FRTP_CD", "")).strip()
                    factor = factors.get(code)
                    if factor is not None:
                        forest_shapes.append((mapping(geom), factor))
                    year = str(attrs.get("갱신년도", "")).strip()
                    years.add(year or "unknown")
                    properties = {"forest_type": str(attrs.get("FRTP_NM", "unknown")),
                        "species": str(attrs.get("KOFTR_NM", "unknown")), "year": year,
                        "density": str(attrs.get("DNST_NM", "unknown")), "tile": path.stem,
                        "fuel_hypothesis": factor}
                    geographic = transform_geometry(to_geo.transform, geom.simplify(12, preserve_topology=True))
                    features.append({"type": "Feature", "geometry": mapping(geographic), "properties": properties})
    fuel = rasterize(forest_shapes, out_shape=elevation.shape, transform=affine, fill=0, dtype="float32")
    soil = rasterize(soil_shapes, out_shape=elevation.shape, transform=affine, fill=0, dtype="uint16") if soil_shapes else np.zeros(elevation.shape, "uint16")
    valid = np.isfinite(elevation) & (fuel > 0)
    if not valid.any():
        raise ValueError("DEM과 임상도가 겹치지 않거나 사용 가능한 숲 격자가 없습니다.")
    # Prefer an interior forest cell over isolated tiny fragments for the first demo.
    neighbours = np.zeros(valid.shape, "uint8")
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            rs, cs = slice(max(0, dr), valid.shape[0] + min(0, dr)), slice(max(0, dc), valid.shape[1] + min(0, dc))
            neighbours[rs, cs] += valid[slice(max(0, -dr), valid.shape[0] - max(0, dr)), slice(max(0, -dc), valid.shape[1] - max(0, dc))]
    indices = np.argwhere(valid & (neighbours == neighbours[valid].max()))
    r, c = indices[len(indices) // 2]
    x, y = affine * (int(c) + .5, int(r) + .5)
    lon, lat = to_geo.transform(x, y)
    west, south = to_geo.transform(bounds[0], bounds[1])
    east, north = to_geo.transform(bounds[2], bounds[3])
    identity = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    terrain_features = []
    elevation_bins = np.where(np.isfinite(elevation), np.floor(elevation / 100), -1).astype("int16")
    for geometry, value in shapes(elevation_bins, mask=np.isfinite(elevation), transform=affine):
        geom = transform_geometry(to_geo.transform, shape(geometry).simplify(25, preserve_topology=True))
        terrain_features.append({"type": "Feature", "geometry": mapping(geom), "properties": {"elevation_band_m": int(value) * 100}})
    manifest = {"version": "daegu-source-v1", "data_sha256": identity, "crs": crs.to_string(),
        "grid_m": resolution, "shape": list(elevation.shape), "transform": list(affine)[:6],
        "bounds_projected": list(bounds), "bounds_wgs84": [west, south, east, north],
        "default_ignition": {"latitude": lat, "longitude": lon}, "forest_features": forest_count,
        "soil_features": soil_count, "known_forest_cells": int(valid.sum()), "years": sorted(years),
        "sources": sources, "soil_used_in_spread": False,
        "fuel_mapping": factors, "warnings": [
            "연구용 가정 계수입니다. 국내 연료모델로 보정되지 않았습니다.",
            "임상도 밖/숲 속성이 없는 셀은 계산에서 제외합니다. 안전한 지역이라는 뜻이 아닙니다.",
            "90m 원본 DEM의 세부 지형 한계를 유지합니다. 도시 전체 자료가 아닙니다.",
            "토양도는 포함 여부만 기록하며 실시간 연료 수분으로 사용하지 않습니다."]}
    # Write products atomically; no source files are edited.
    np.savez_compressed(output / "grid.next.npz", elevation=elevation, fuel=fuel, soil=soil, valid=valid)
    (output / "grid.next.npz").replace(output / "grid.npz")
    manifest["grid_sha256"] = digest_file(output / "grid.npz")
    for name, value in (("forest.geojson", collection(features)), ("terrain.geojson", collection(terrain_features)), ("manifest.json", manifest)):
        temporary = output / (name + ".next")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(output / name)
    return manifest


def load_manifest(output: Path):
    return json.loads((output / "manifest.json").read_text(encoding="utf-8"))
