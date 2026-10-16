"""Live/dead extension of the user-requested historical-mask stationary shared/ridge fit."""
from pathlib import Path
import os,sys,json,time,subprocess,traceback,hashlib
import xml.etree.ElementTree as ET
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from core import colony,fitting,assumptions,transfer
PYTHON=sys.executable
PARAMETERS=['xeq','speed','K','radius','rho0','m0','vinit','fG','oxygen_ratio','oxygen_half','oxygen_hill','G1_reference_rate','death_rate','dead_duration_hours','initial_dead_fraction']
NATURAL_BOUNDS=np.array([[.55,.995],[.1,1e5],[.03,100],[3,120],[1e-6,.005],[1,1000],[.25,4],[.02,.98],[.01,100],[.001,100],[.01,100],[.1,24.],[1e-4,3.],[.25,72.],[1e-4,.75]])
BOUNDS=np.log(NATURAL_BOUNDS);COEF=np.array([.5,.1,.1,.1,.1,.1]);ALPHAS=[0.,1.,10.,100.,1000.]
AREA=1100*1400;COUNT_OFFSET=float(np.log(AREA));REPLICATES=2;TIMEOUT=900
SHARED_STARTS=16;RIDGE_STARTS_PER_ALPHA=12;OPTIMIZER_SECONDS=240;STEPS=600;NPAR=15
NATIVE_SEED_BASE=2026101600
def read(path):return json.loads(Path(path).read_text())
def write(path,value):fitting.atomic_json(path,value)
def vectors(x):
 x=np.asarray(x,float)
 if x.shape not in [(NPAR,),(2*NPAR,)]:raise ValueError('Expected shared or two-ploidy coefficient vector')
 return (x,x) if len(x)==NPAR else (x[:NPAR],x[NPAR:])
def rate(x,oxygen):
 return float(np.exp(x[11])*fitting.medium_multiplier(float(oxygen),20.5,*np.exp(x[8:11])))

class Data:
 def __init__(self):
  self.rows=pd.read_csv(ROOT/'inputs/observations.csv');a=np.load(ROOT/'inputs/observations.npz')
  self.obs=a['observed'];self.scales=a['scales'];self.weights=a['weights'];self.n=len(self.rows)
  self.times=self.rows.time_days.to_numpy(float);self.groups=self.rows.group.to_numpy();self.oxygen=self.rows.oxygen.to_numpy(float)
  self.oxygen_values=sorted(np.unique(self.oxygen).tolist());self.plans=[];self.common_plans=[]
  for oi,o in enumerate(self.oxygen_values):
   allidx=np.flatnonzero(self.oxygen==o);times=np.unique(self.times[allidx]);duration=float(times.max());dt=duration/STEPS if duration>0 else 1/120
   base=dict(oxygen=o,oxygen_index=oi,times=times,duration=duration,dt=dt)
   self.common_plans.append(dict(base,indices=allidx,lookup=np.searchsorted(times,self.times[allidx]),group='both'))
   for gi,g in enumerate(['2N','4N']):
    idx=np.flatnonzero((self.oxygen==o)&(self.groups==g))
    self.plans.append(dict(base,indices=idx,lookup=np.searchsorted(times,self.times[idx]),group=g,group_index=gi))
  self.episodes=[]
  for gi,g in enumerate(['2N','4N']):
   ep=self.rows[self.rows.group.eq(g)].groupby('episode_id',sort=False)
   for eid,frame in ep:self.episodes.append(dict(id=eid,group=g,group_index=gi,oxygen=float(frame.oxygen.iloc[0]),duration=float(frame.time_days.max()),weight=.5/len(ep)))

def evaluate(data,x,alpha):
 start=time.monotonic();pred=np.full((data.n,30),np.nan);traces={};xx=vectors(x)
 try:
  for p in (data.common_plans if len(x)==NPAR else data.plans):
   p=dict(p,group_index=p.get("group_index",0))
   key=(p['group_index'],p['oxygen']);r=rate(xx[p['group_index']],p['oxygen'])
   v,t=colony.simulate_with_geometry(np.exp(xx[p['group_index']][:8]),r,p['times'],p['dt'],mu=float(np.exp(xx[p['group_index']][12])),dead_duration_hours=float(np.exp(xx[p['group_index']][13])),initial_dead_fraction=float(np.exp(xx[p['group_index']][14])),observation_area=AREA)
   if not np.isfinite(v).all():return dict(loss=1e25,data_loss=1e25,assumption_penalty=0.,ridge_penalty=0.,parameter_difference=0.,count_offset=COUNT_OFFSET,weighted_components=[0.]*6,invalid=True)
   pred[p['indices']]=v[p['lookup']];traces[key]=t
   if len(x)==NPAR:traces[(1,p['oxygen'])]=t
  loss,b,parts=fitting.composite_score(pred,data.obs,data.scales,data.weights,COEF,offset=COUNT_OFFSET)
  diagnostics=[];penalty=0.
  for episode in data.episodes:
   q=assumptions.summarize_trace(traces[(episode['group_index'],episode['oxygen'])],episode['duration']);penalty+=episode['weight']*q['penalty']
  difference=float(np.mean(((xx[0]-xx[1])/np.diff(BOUNDS,axis=1).ravel())**2));ridge=float(alpha*difference)
  return dict(loss=loss+penalty+ridge,data_loss=loss,assumption_penalty=penalty,ridge_penalty=ridge,parameter_difference=difference,count_offset=b,weighted_components=parts.tolist(),alpha=alpha,evaluation_seconds=time.monotonic()-start)
 except (ValueError,OverflowError,FloatingPointError):return dict(loss=1e25,data_loss=1e25,assumption_penalty=0.,ridge_penalty=0.,parameter_difference=0.,count_offset=COUNT_OFFSET,weighted_components=[0.]*6,invalid=True)


def candidate(stage,index):return read(ROOT/(stage+'_candidates.json'))[index]
def fit(stage,index):
 data=Data();c=candidate(stage,index);d=ROOT/'candidates'/c['id'];d.mkdir(parents=True,exist_ok=True);bounds=BOUNDS if stage=='shared' else np.tile(BOUNDS,(2,1));initial=np.asarray(c['initial']);rng=np.random.default_rng(c['seed'])
 rejected=0
 while rejected<25 and evaluate(data,initial,c['alpha'])['loss']>=1e24:
  initial=bounds[:,0]+rng.random(len(bounds))*np.diff(bounds,axis=1).ravel();rejected+=1
 write(d/'initialization.json',dict(candidate=c,rejected_invalid_initials=rejected,actual_initial=initial.tolist()))
 fitting.bounded_search(lambda x:evaluate(data,x,c['alpha']),initial,bounds,OPTIMIZER_SECONDS,d/'checkpoint.json')

def finalize(stage,index):
 c=candidate(stage,index);d=ROOT/'candidates'/c['id'];d.mkdir(parents=True,exist_ok=True)
 if not (d/'checkpoint.json').exists():write(d/'outcome.json',dict(candidate=c,status='missing_checkpoint'));return
 checkpoint=read(d/'checkpoint.json')
 if checkpoint['loss']>=1e24:write(d/'outcome.json',dict(candidate=c,status='invalid_checkpoint'));return
 data=Data();value=evaluate(data,np.array(checkpoint['x']),c['alpha']);value.update(candidate=c,x=checkpoint['x'],fit_evaluations=read(str(d/'checkpoint.json')+'.status.json')['evaluations']);write(d/'final.json',value)
 slots=[];plans=data.common_plans if stage=='shared' else data.plans
 for rep in range(REPLICATES):
  for p in plans:
   slots.append(dict(group=p['group'],group_index=p.get('group_index',0),oxygen=p['oxygen'],oxygen_index=p['oxygen_index'],replicate=rep,seed=NATIVE_SEED_BASE+100*rep+p['oxygen_index'],indices=p['indices'].tolist(),times_days=p['times'].tolist(),lookup=p['lookup'].tolist(),duration_days=p['duration']))
 write(d/'slots.json',slots)

def simulate(stage,index,slot_index):
 c=candidate(stage,index);d=ROOT/'candidates'/c['id'];sd=d/'simulations'/f'{slot_index:03}';sd.mkdir(parents=True,exist_ok=True);result=dict(candidate_id=c['id'],stage=stage,slot_index=slot_index,engine_threads=1,engine_timeout_seconds=TIMEOUT);started=time.monotonic()
 try:
  frozen=read(d/'final.json');slot=read(d/'slots.json')[slot_index];xx=vectors(frozen['x'])[slot['group_index']];shape=[1100,1400];scale=np.sqrt(1.5);domain=[shape[1]*scale,shape[0]*scale];crop=[-shape[1]/2,-shape[0]/2];times=np.array(slot['times_days'])*1440
  case=sd/'case';meta=transfer.export_case(case,np.exp(xx[:8]),rate(xx,slot['oxygen']),slot['seed'],times,domain,death_per_day=float(np.exp(xx[12])),dead_duration_hours=float(np.exp(xx[13])),initial_dead_fraction=float(np.exp(xx[14])))
  engine=ENGINE;before=time.monotonic()
  with (sd/'engine.log').open('w') as log:
   done=subprocess.run([str(engine),'PhysiCell_settings.xml'],cwd=case,stdout=log,stderr=subprocess.STDOUT,timeout=TIMEOUT,env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1'))
  result['engine_seconds']=time.monotonic()-before
  if done.returncode:raise RuntimeError(f'Engine returncode{done.returncode}')
  outputs=[]
  for path in sorted((case/'output').glob('output*.xml')):
   try:t=float(ET.parse(path).getroot().find('.//current_time').text);outputs.append((t,path))
   except (ValueError,AttributeError):pass
  if not outputs:raise RuntimeError('No timed simulator snapshots')
  values=[];snapshots=[];measurement=time.monotonic()
  for t in times:
   actual,path=min(outputs,key=lambda a:abs(a[0]-t))
   if abs(actual-t)>.500001:raise RuntimeError(f'No matchingtime{t},nearest{actual}')
   v,m=transfer.snapshot(path,domain,shape,crop);values.append(v);snapshots.append(dict(requested_minutes=float(t),actual_minutes=actual,path=str(path.relative_to(ROOT)),metadata=m))
  arr=np.array(values);np.savez_compressed(sd/'observables.npz',indices=np.array(slot['indices']),predicted=arr[np.array(slot['lookup'])],trajectory_predicted=arr,times_minutes=times)
  result.update(status='complete',slot=slot,initialization=meta,snapshots=snapshots,measurement_seconds=time.monotonic()-measurement,domain_size=domain,field_shape=shape,crop_origin=crop)
 except Exception as error:result.update(status='failed',error=repr(error),traceback=traceback.format_exc())
 result['wall_seconds']=time.monotonic()-started;write(sd/'outcome.json',result)

def score_candidate(c):
 d=ROOT/'candidates'/c['id'];data=Data()
 if not (d/'final.json').exists():return dict(candidate=c,status='missing_final')
 final=read(d/'final.json');slots=read(d/'slots.json');pred=np.full((REPLICATES,data.n,30),np.nan);seen=np.zeros((REPLICATES,data.n),int);fail=[]
 for si,slot in enumerate(slots):
  sd=d/'simulations'/f'{si:03}'
  if not (sd/'outcome.json').exists() or read(sd/'outcome.json')['status']!='complete':fail.append(si);continue
  a=np.load(sd/'observables.npz');idx=a['indices'].astype(int);pred[slot['replicate'],idx]=a['predicted'];seen[slot['replicate'],idx]+=1
 if fail or np.any(seen!=1) or not np.isfinite(pred).all():return dict(candidate=c,status='incomplete_simulator_support',failed_slots=fail,completed_slots=len(slots)-len(fail),requested_slots=len(slots))
 reps=[];groups=[]
 for r in range(REPLICATES):
  loss,b,parts=fitting.composite_score(pred[r],data.obs,data.scales,data.weights,COEF,offset=COUNT_OFFSET);gg={}
  for g in ['2N','4N']:
   w=data.weights.copy();w[data.groups!=g]=0;w*=2;gg[g]=fitting.composite_score(pred[r],data.obs,data.scales,w,COEF,offset=COUNT_OFFSET)[0]
  reps.append(dict(replicate=r,data_loss=loss,weighted_components=parts.tolist(),group_losses=gg));groups.append(gg)
 loss=float(np.mean([r['data_loss'] for r in reps]));sd=float(np.std([r['data_loss'] for r in reps],ddof=1)) if REPLICATES>1 else 0.;parts=np.mean([r['weighted_components'] for r in reps],axis=0)
 result=dict(candidate=c,status='complete',x=final['x'],count_offset=COUNT_OFFSET,simulator_data_loss=loss,simulator_data_loss_seed_sd=sd,replicates=reps,approximation_data_loss=final['data_loss'],assumption_penalty=final['assumption_penalty'],ridge_penalty=final['ridge_penalty'],parameter_difference=final['parameter_difference'],simulator_penalized_loss=loss+final['ridge_penalty'],search_objective=final['loss'],simulator_components=parts.tolist(),group_losses={g:float(np.mean([v[g] for v in groups])) for g in ['2N','4N']})
 np.savez_compressed(d/'simulated.npz',predicted=pred.mean(axis=0),replicate_predicted=pred);write(d/'score.json',result);return result

def score(stage):
 candidates=read(ROOT/(stage+'_candidates.json'));results=[score_candidate(c) for c in candidates];write(ROOT/(stage+'_scores.json'),results)
 if stage=='shared':
  good=sorted([v for v in results if v['status']=='complete'],key=lambda v:(v['simulator_data_loss'],v['candidate']['id']))
  if not good:raise RuntimeError('No fully scored sharedparent; ridgeblocked')
  write(ROOT/'shared_best.json',good[0])
 else:
  shared=read(ROOT/'shared_best.json');pool=[v for v in results if v['status']=='complete']+[shared];path=[];assigned=[]
  for alpha in ALPHAS:
   ranked=[]
   for v in pool:
    q=dict(v);q.update(evaluation_alpha=alpha,ridge_penalty=alpha*v['parameter_difference'],simulator_penalized_loss=v['simulator_data_loss']+alpha*v['parameter_difference']);ranked.append(q)
   ranked.sort(key=lambda v:(v['simulator_penalized_loss'],v['candidate']['id']));path.append(dict(alpha=alpha,winner=ranked[0]))
   local=[v for v in ranked if v['candidate']['stage']=='shared' or v['candidate']['alpha']==alpha];assigned.append(dict(alpha=alpha,winner=local[0]))
  write(ROOT/'results.json',dict(shared_best=shared,ridge_path=assigned,pooled_path=path,shared_candidates=read(ROOT/'shared_scores.json'),ridge_candidates=results,parameter_names=PARAMETERS,natural_bounds=NATURAL_BOUNDS.tolist(),penalty='alpha * mean(((log(theta_2N)-log(theta_4N))/(log(upper)-log(lower)))^2)',count_offset='fixed commonlog1540000fieldarea; nofitcalibration',replicates=REPLICATES))
