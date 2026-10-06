"""Matched observation operators; pixels, 30px reflection/border, radius10 closing."""
import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from skimage.morphology import disk
from skimage.measure import regionprops_table
Q=np.arange(.02,1,.04)
def measure(binary, centers, areas):
    h,w=binary.shape
    envelope=ndi.binary_closing(np.pad(binary,30,mode='reflect'),structure=disk(10))[30:-30,30:-30]
    interior=envelope[30:-30,30:-30]
    coverage=interior.mean()
    dist=ndi.distance_transform_edt(~envelope)
    yy,xx=np.mgrid[30:h-30:4,30:w-30:4]
    keep=~envelope[yy,xx]; y=yy[keep];x=xx[keep]
    if len(x)<100:
        iy,ix=np.nonzero(~interior)
        y=iy+30; x=ix+30
    gap=0.0 if coverage == 1.0 else np.nan
    if len(x)>0:
        d=dist[y,x]; censor=np.minimum.reduce([x-29,w-30-x,y-29,h-30-y]).astype(float)
        tt=np.minimum(d,censor);event=d<=censor
        order=np.argsort(tt);tt=tt[order];event=event[order]
        unique,first,n=np.unique(tt,return_index=True,return_counts=True)
        deaths=np.add.reduceat(event.astype(int),first)
        survival=np.cumprod(1-deaths/(len(tt)-first))
        hit=np.flatnonzero(survival<=.5)
        if len(hit): gap=unique[hit[0]]
    ce=np.nan
    if len(centers)>1: ce=2*np.sqrt(len(centers)/(w*h))*cKDTree(centers).query(centers,k=2)[0][:,1].mean()
    return dict(coverage=float(coverage),gap=float(gap),ce=float(ce),areas=np.asarray(areas,dtype=float),n=len(areas),width=w,height=h)
def mask_measure(mask):
    p=regionprops_table(mask,properties=['area','centroid'])
    return measure(mask>0,np.column_stack([p['centroid-1'],p['centroid-0']]),p['area'])
def aggregate(fields,seed=193):
    def calc(fs):
        a=np.concatenate([f['areas'] for f in fs]); q=np.quantile(np.log(a/a.mean()),Q) if len(a) else np.full(25,np.nan)
        vals=np.array([[f['coverage'],np.log(max(f['gap'],1.0)) if np.isfinite(f['gap']) and f['gap']>=0 else np.nan,f['ce']] for f in fs])
        out=np.array([np.mean(v[np.isfinite(v)]) if np.isfinite(v).any() else np.nan for v in vals.T])
        return np.r_[out,q]
    val=calc(fields);rng=np.random.default_rng(seed)
    boot=np.array([calc([fields[i] for i in rng.integers(len(fields),size=len(fields))]) for _ in range(300)])
    sd=np.array([np.std(v[np.isfinite(v)],ddof=1) if np.isfinite(v).sum()>1 else 0. for v in boot.T])
    se=np.sqrt(sd**2+np.r_[.05,.2,.08,np.full(25,.08)]**2)
    return val,se
