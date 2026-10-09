from dataclasses import replace
from io import BytesIO
import pytest
from PIL import Image
from app.alerts import AlarmGate
from app.config import Settings
from app.policy import filter_predictions
from app.security import hash_password,verify_password,RateLimiter
from app.detector import decode_frame

def test_gate_requires_time_and_hits():
    gate=AlarmGate(Settings())
    assert not gate.observe('a',True,0)['trigger']
    assert not gate.observe('a',True,.1)['trigger']
    assert not gate.observe('a',True,.2)['trigger']
    assert gate.observe('a',True,1.2)['trigger']
    assert not gate.observe('a',True,2)['trigger']

def test_single_signal_cannot_alarm():
    gate=AlarmGate(Settings())
    for t in range(10):
        assert not gate.observe('a',t==2,t)['trigger']

def test_stale_frames_reset_confirmation_and_cooldown_survives_gap():
    gate=AlarmGate(Settings())
    gate.observe('a',True,0);gate.observe('a',True,1)
    assert not gate.observe('a',True,10)['trigger']
    gate.observe('a',True,11)
    assert gate.observe('a',True,12)['trigger']
    for t in (20,21,22):
        assert not gate.observe('a',True,t)['trigger']

def test_separate_cameras_do_not_share_confirmation():
    gate=AlarmGate(Settings())
    assert not gate.observe('a',True,0)['trigger']
    assert not gate.observe('b',True,1)['trigger']
    assert not gate.observe('a',True,2)['trigger']

def test_clear_frames_rearm_after_cooldown():
    gate=AlarmGate(Settings(alarm_cooldown_seconds=3))
    for t in (0,1,2):r=gate.observe('a',True,t)
    assert r['trigger']
    for t in (3,4,5,6,7):gate.observe('a',False,t)
    for t in (8,9,10):r=gate.observe('a',True,t)
    assert r['trigger']

def test_policy_never_invents_fire_from_smoke():
    policy={'strong_conf':.25,'weak_conf':.22,'weak_support':'near_strong_fire','support_radius':.4,'duplicate_iou':.45,'smoke_conf':.25}
    predictions=[{'class_id':0,'score':.9,'xyxy':[0,0,10,10]},{'class_id':1,'score':.23,'xyxy':[0,0,10,10]}]
    assert filter_predictions(predictions,policy,(100,100))==[0]
    predictions.append({'class_id':1,'score':.9,'xyxy':[20,0,30,10]})
    assert filter_predictions(predictions,policy,(100,100))==[0,1,2]

def test_password_hash_and_invalid_frame():
    encoded=hash_password('good password')
    assert verify_password('good password',encoded)
    assert not verify_password('wrong password',encoded)
    with pytest.raises(ValueError):decode_frame(b'invalid',Settings())

def test_oversized_dimensions_rejected_before_decode():
    data=BytesIO();Image.new('RGB',(5000,16)).save(data,format='PNG')
    with pytest.raises(ValueError):decode_frame(data.getvalue(),Settings())

def test_rate_limit():
    limiter=RateLimiter();limiter.check('x',1,60)
    with pytest.raises(Exception) as e:limiter.check('x',1,60)
    assert e.value.status_code==429

def test_production_rejects_development_defaults(monkeypatch):
    monkeypatch.setenv('EMBER_ENVIRONMENT','production')
    with pytest.raises(ValueError):Settings.from_env()
