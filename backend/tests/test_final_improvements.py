import json
from pathlib import Path
import numpy as np
import pytest
from app.policy import refine_predictions
from app.spread.engine import cellular_automata, neighbour_slices

RULE={'alpha':.5,'iou_threshold':.5,'min_score':.2,'score_ratio':.5,'class_ids':[1]}

def test_refinement_preserves_input_classes_scores_count_and_smoke():
    p=[{'class_id':1,'score':.8,'xyxy':[0.,0.,10.,10.]},
       {'class_id':1,'score':.4,'xyxy':[1.,0.,11.,10.]},
       {'class_id':0,'score':.7,'xyxy':[0.,0.,15.,15.]}]
    before=json.dumps(p);result=refine_predictions(p,[0,2],RULE)
    assert json.dumps(p)==before and len(result)==2
    assert result[0]['class_id']==1 and result[0]['score']==.8
    assert result[0]['xyxy'][0]==pytest.approx(.1)
    assert result[1]==p[2]
    assert refine_predictions(p,[0,2])==[p[0],p[2]]

def test_smoke_cannot_move_fire_and_empty_input_cannot_create_detection():
    p=[{'class_id':1,'score':.8,'xyxy':[0,0,10,10]},
       {'class_id':0,'score':.9,'xyxy':[1,1,11,11]}]
    assert refine_predictions(p,[0],RULE)==[p[0]]
    assert refine_predictions([],[],RULE)==[]
    with pytest.raises(ValueError):refine_predictions(p,[0],{**RULE,'alpha':float('nan')})

def dense_reference(elevation,fuel,valid,ignition,weather,horizons,runs=8,seed=42,cell_m=90,ros=6):
    from math import atan2,cos,pi,hypot
    rng=np.random.default_rng(seed);rows,cols=valid.shape
    age=np.full((runs,rows,cols),-1,dtype='int16');age[:,ignition[0],ignition[1]]=0
    dt=1/3;outputs={};transitions=[]
    moisture=np.clip(1.2-.008*weather['humidity_pct'],.35,1.2)*np.exp(-min(weather['rain_mm'],10)*.35)
    wind_to=(weather['wind_from_deg']+180)%360
    for dr in (-1,0,1):
        for dc in (-1,0,1):
            if dr==dc==0:continue
            source,destination=neighbour_slices(rows,cols,dr,dc);distance=cell_m*hypot(dr,dc)
            angle=atan2(dc,-dr)*180/pi%360
            wind=np.exp(np.clip(.13*weather['wind_speed_ms']*cos((angle-wind_to)*pi/180),-2,2))
            slope=np.clip((elevation[destination]-elevation[source])/distance,-.7,.7)
            hazard=ros*fuel[destination]*moisture*wind*np.exp(2.5*slope)/distance
            p=np.where(valid[source]&valid[destination],np.clip(1-np.exp(-hazard*dt),0,.7),0)
            transitions.append((source,destination,p))
    checkpoints={int(round(h/dt)):h for h in horizons}
    for step in range(1,max(checkpoints)+1):
        active=(age>=0)&(age<24);survival=np.ones(age.shape,dtype='float32')
        for source,destination,p in transitions:survival[(slice(None),)+destination]*=1-active[(slice(None),)+source]*p
        ignite=(age<0)&valid[None,...]&(rng.random(age.shape)<(1-survival))
        age[age>=0]+=1;age[ignite]=0
        if step in checkpoints:outputs[checkpoints[step]]=(age>=0).mean(axis=0).astype('float32')
    return outputs

@pytest.mark.parametrize('density',[0,.1,.4,1])
@pytest.mark.parametrize('seed',[0,42,91])
def test_sparse_ca_bitwise_equal_to_original_dense_algorithm(density,seed):
    rng=np.random.default_rng(17);valid=rng.random((13,17))<density;valid[6,8]=True
    elevation=rng.normal(100,10,valid.shape).astype('float32');fuel=np.ones(valid.shape,'float32')
    weather={'humidity_pct':40,'rain_mm':0,'wind_from_deg':270,'wind_speed_ms':3}
    args=(elevation,fuel,valid,(6,8),weather,[3,10])
    a=dense_reference(*args,runs=8,seed=seed);b=cellular_automata(*args,runs=8,seed=seed)
    assert all(np.array_equal(a[k],b[k]) for k in a)
