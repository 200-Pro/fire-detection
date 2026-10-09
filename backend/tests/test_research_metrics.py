import pytest
from app.research_metrics import fire_metrics,perimeter_metrics,coverage_audit
import numpy as np

def test_fire_matching_one_to_one_and_empty_truth():
    pred=[{"score":.8,"xyxy":[0,0,10,10]},{"score":.7,"xyxy":[0,0,10,10]}]
    r=fire_metrics(pred,[[0,0,10,10]])
    assert (r["tp"],r["fp"],r["fn"])==(1,1,0)
    assert fire_metrics([],[])["recall"] is None
    assert fire_metrics(pred,[])["fp"]==2

def test_perimeter_metrics_projected_equal_and_disjoint():
    a={"type":"Polygon","coordinates":[[[128.6,35.8],[128.601,35.8],[128.601,35.801],[128.6,35.801],[128.6,35.8]]]}
    assert perimeter_metrics(a,a)["iou"]==pytest.approx(1)
    b={"type":"Polygon","coordinates":[[[128.7,35.8],[128.701,35.8],[128.701,35.801],[128.7,35.801],[128.7,35.8]]]}
    assert perimeter_metrics(a,b)["iou"]==0

def test_disconnected_coverage_not_assumed_safe():
    valid=np.zeros((5,5),bool);valid[0,0]=True;valid[3:5,3:5]=True
    r=coverage_audit({"valid":valid,"elevation":np.ones((5,5))},{"grid_m":90,"data_sha256":"x"})
    assert r["connected_components"]==2 and r["known_forest_cells"]==5
