import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from app.spread.terrain import read_dem_tiles

def tile(path,x,value,res=90):
    with rasterio.open(path,"w",driver="GTiff",height=2,width=2,count=1,dtype="float32",
                       crs="EPSG:5179",transform=from_origin(x,1800000,res,res)) as out:
        out.write(np.full((2,2),value,dtype="float32"),1)

def test_mosaic_same_resolution_preserves_tiles(tmp_path):
    a,b=tmp_path/"a.tif",tmp_path/"b.tif"
    tile(a,1100000,10);tile(b,1100180,20)
    grid,_,affine,res,_=read_dem_tiles([a,b])
    assert grid.shape==(2,4) and res==90 and affine.c==1100000
    assert np.all(grid[:,:2]==10) and np.all(grid[:,2:]==20)

def test_mosaic_rejects_resolution_and_alignment_changes(tmp_path):
    a,b=tmp_path/"a.tif",tmp_path/"b.tif";tile(a,1100000,10)
    tile(b,1100181,20)
    with pytest.raises(ValueError):
        read_dem_tiles([a,b])
    tile(b,1100180,20,res=30)
    with pytest.raises(ValueError):
        read_dem_tiles([a,b])
