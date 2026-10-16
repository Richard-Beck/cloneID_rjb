"""Continuation of the live/dead baseline through the requested WGD-state model."""
from pathlib import Path
import json,os,sys,time,traceback
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import xlogy, expit, log_expit, logit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from core import fitting,colony

PYTHON=sys.executable
# Parent scores are resolved only from the new run by workflow.py.
NAMES=['xeq','speed','K','radius','vinit','fG','oxygen_ratio','oxygen_half','oxygen_hill','G1_reference_rate','death_rate','dead_duration_hours','initial_dead_fraction']
NB=np.array([[.55,.995],[.1,1e5],[.03,100],[3,120],[.25,4],[.02,.98],[.01,100],[.001,100],[.01,100],[.1,24],[1e-4,3],[.25,72],[1e-4,.75]])
BOUNDS=np.vstack([np.tile([0.,1.],(5,1)),np.log([[1e-6,.005],[1,1000]]),np.log(NB),np.log(NB)])
BOUNDS[2]=np.log([1e-12,.5])
PARAMETERS=['founder_high_2N','founder_high_4N','log_w','dmax','q','log_rho0','log_m0']+['log_'+s+'_'+n for s in ['low','high'] for n in NAMES]
ALPHAS=[0.,.1,1.,10.]
COEF=np.array([.5,.1,.1,.1,.1,.1])
AREA=1540000
B=float(np.log(AREA))
REPS=2
STEPS=600
FIT_SECONDS=360
REFINE_SECONDS=315
TIMEOUT=660
STARTS_PER_FAMILY_ALPHA=4
SEED_BASE=2026102000

def read(path):return json.loads(Path(path).read_text())
def write(path,value):fitting.atomic_json(path,value)
def clean(value):
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [clean(v) for v in value]
    if isinstance(value,np.integer):return int(value)
    if isinstance(value,np.floating):return float(value)
    return value
def rate(v,oxygen):return float(v[9]*fitting.medium_multiplier(oxygen,20.5,*v[6:9]))
def state9(v):return np.r_[v[:6],v[10:13]]
def state8(v,nat):return np.r_[v[:4],nat['rho0'],nat['m0'],v[4:6]]
def decode(x,family):
    x=np.asarray(x,float)
    if x.shape!=(33,):raise ValueError('Expected 33 state-model coordinates')
    return dict(founder_high={'2N':float(x[0]),'4N':float(x[1])},w=0. if family in ['null','no_wgd'] else float(np.exp(x[2])),dmax=0. if family=='null' else float(x[3]),q=1. if family in ['null','no_protection'] else float(x[4]),rho0=float(np.exp(x[5])),m0=float(np.exp(x[6])),low=np.exp(x[7:20]),high=np.exp(x[20:33]))

class Data:
    def __init__(self,steps=STEPS):
        self.rows=pd.read_csv(ROOT/'inputs/observations.csv')
        a=np.load(ROOT/'inputs/observations.npz')
        self.obs=a['observed'];self.scales=a['scales'];self.weights=a['weights']
        self.n=len(self.rows);self.groups=self.rows.group.to_numpy()
        self.episodes=read(ROOT/'inputs/episodes.json');self.assays=read(ROOT/'inputs/assays.json')
        self.byid={p['episode_id']:p for p in self.episodes}
        self.neps={g:sum(p['founding_group']==g for p in self.episodes) for g in ['2N','4N']}
        self.dt={o:float(self.rows.loc[self.rows.oxygen.eq(o),'time_days'].max())/steps for o in {p['oxygen'] for p in self.episodes}}
        self.plans={p['episode_id']:np.unique(np.round(p['needed_times_days']+[q['time_days'] for q in self.assays if q['episode_id']==p['episode_id']],10)) for p in self.episodes}

def evaluate(data,x,alpha,family,save=None,corrections=None,correction=None):
    from wgd_colony import simulate_two_state
    started=time.monotonic();nat=decode(x,family)
    predicted=np.full((data.n,30),np.nan);traces={};fractions={};closure=[];cache={};latent={}
    corrections=corrections or {}
    if correction is not None:corrections=dict(zip(correction['episode_ids'],correction['delta_per_day']))
    anchor=nat['w']==0 and nat['dmax']==0 and np.array_equal(nat['low'],nat['high'])
    try:
        for episode in data.episodes:
            eid=episode['episode_id'];parent=episode['parent_episode_id']
            z=float(logit(nat['founder_high'][episode['founding_group']])) if parent is None else float(np.interp(episode['parent_transfer_time_days'],traces[parent][:,0],latent[parent]))
            if not np.isfinite(z):raise ValueError('Founder fractions must be strictly interior')
            f=float(expit(z));fractions[eid]=f;oxygen=episode['oxygen'];ts=data.plans[eid]
            dl=nat['dmax']*float(np.clip(1-oxygen/20.5,0,1));dh=nat['q']*dl
            probe=float(np.clip(f,1e-10,1-1e-10))
            key=(oxygen,probe,tuple(ts))
            if key in cache:values,rawtrace=cache[key];values=values.copy();trace=rawtrace.copy()
            else:
                values,trace=simulate_two_state(state9(nat['low']),state9(nat['high']),rate(nat['low'],oxygen),rate(nat['high'],oxygen),nat['rho0'],nat['m0'],probe,nat['w'],dl,dh,ts,dt=data.dt[oxygen],observation_area=AREA)
                cache[key]=(values.copy(),trace.copy())
            if not np.isfinite(values).all() or not np.isfinite(trace).all() or np.any(trace[:,1:3]<=0):
                return dict(loss=1e25,data_loss=1e25,invalid=True,invalid_episode=eid)
            relative_growth=np.log(trace[:,2]/trace[0,2])-np.log(trace[:,1]/trace[0,1])
            if anchor:relative_growth[:]=0.
            zz=z+relative_growth+float(corrections.get(eid,0.))*trace[:,0]
            latent[eid]=zz;trace[:,3]=expit(zz)
            traces[eid]=trace;indices=np.asarray(episode['observation_rows'],int)
            observation_times=data.rows.time_days.to_numpy()[indices]
            lookup=np.argmin(abs(ts[:,None]-observation_times[None,:]),axis=0)
            if np.max(abs(ts[lookup]-observation_times),initial=0)>1e-8:raise ValueError('Observation-time mapping mismatch')
            predicted[indices]=values[lookup]
            relative=trace[:,7]/(2*trace[:,22]);violation=np.maximum(0,1.25/np.sqrt(3)-relative)
            duration=trace[-1,0]
            penalty=float(np.trapz((violation/.05)**2,trace[:,0])/duration) if duration else float((violation[0]/.05)**2)
            closure.append(dict(episode_id=eid,penalty=penalty,min_relative_spacing=float(relative.min()),weight=.5/data.neps[episode['founding_group']]))
        if anchor:
            # Exact unchanged shared microscopy operator and oxygen-specific mesh.
            v=nat['low']
            for oxygen in data.dt:
                indices=np.flatnonzero(data.rows.oxygen.to_numpy()==oxygen)
                times=np.unique(data.rows.time_days.to_numpy()[indices])
                values,_=colony.simulate_with_geometry(state8(v,nat),rate(v,oxygen),times,dt=data.dt[oxygen],mu=v[10],dead_duration_hours=v[11],initial_dead_fraction=v[12],observation_area=AREA)
                predicted[indices]=values[np.searchsorted(times,data.rows.time_days.to_numpy()[indices])]
        loss,offset,parts=fitting.composite_score(predicted,data.obs,data.scales,data.weights,COEF,offset=B)
        assays=[]
        for assay in data.assays:
            az=float(np.interp(assay['time_days'],traces[assay['episode_id']][:,0],latent[assay['episode_id']]))
            k=assay['k'];n=assay['n'];lp=float(log_expit(az));lq=float(log_expit(-az))
            deviance=float(2*(xlogy(k,k/n)+xlogy(n-k,1-k/n)-k*lp-(n-k)*lq))
            assays.append(dict(id=assay['id'],episode_id=assay['episode_id'],time_days=assay['time_days'],k=k,n=n,predicted_high=float(expit(az)),log_odds=az,log_p=lp,log_q=lq,deviance=deviance))
        assay_loss=float(np.mean([q['deviance'] for q in assays]))
        difference=float(np.mean(((x[7:20]-x[20:33])/np.log(1.5))**2))
        penalty=sum(q['weight']*q['penalty'] for q in closure)
        result=dict(loss=loss+assay_loss+alpha*difference+penalty,data_loss=loss,assay_deviance=assay_loss,assumption_penalty=penalty,ridge_penalty=alpha*difference,parameter_difference=difference,count_offset=offset,weighted_components=parts.tolist(),alpha=alpha,family=family,seed_fractions=fractions,assays=assays,natural_parameters=clean(nat),closure=closure,evaluation_seconds=time.monotonic()-started,valid=True,latent_policy='continuous log odds; probe clipping only for within-passage numerical response, not latent probability or assay likelihood',native_selection_corrected=bool(corrections))
        if save:
            save=Path(save);save.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(save/'approximation.npz',predicted=predicted,**{'trace_'+str(i):traces[p['episode_id']] for i,p in enumerate(data.episodes)},**{'latent_'+str(i):latent[p['episode_id']] for i,p in enumerate(data.episodes)})
            write(save/'episode_trace_index.json',[p['episode_id'] for p in data.episodes])
        return result
    except (ValueError,OverflowError,FloatingPointError,ZeroDivisionError):
        return dict(loss=1e25,data_loss=1e25,invalid=True,error=traceback.format_exc())


def candidate(index):return read(ROOT/'candidates.json')[index]
