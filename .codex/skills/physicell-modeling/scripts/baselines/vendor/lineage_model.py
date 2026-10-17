"""Live/dead extension of the user-requested historical-mask stationary shared/ridge fit."""
from pathlib import Path
import os,sys,json,time,subprocess,traceback,hashlib
import xml.etree.ElementTree as ET
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from core import colony,fitting,assumptions,transfer
import native_support as support
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
 while rejected<25 and evaluate(data,initial,c['alpha']).get('invalid',False):
  initial=bounds[:,0]+rng.random(len(bounds))*np.diff(bounds,axis=1).ravel();rejected+=1
 write(d/'initialization.json',dict(candidate=c,rejected_invalid_initials=rejected,actual_initial=initial.tolist()))
 def objective(x):
  value=evaluate(data,x,c['alpha'])
  return None if value.get('invalid',False) or value.get('valid') is False or not np.isfinite(value.get('loss',np.nan)) else value
 fitting.bounded_search(objective,initial,bounds,OPTIMIZER_SECONDS,d/'checkpoint.json')

def finalize(stage,index):
 c=candidate(stage,index);d=ROOT/'candidates'/c['id'];d.mkdir(parents=True,exist_ok=True)
 if not (d/'checkpoint.json').exists():write(d/'outcome.json',dict(candidate=c,status='missing_checkpoint'));return
 checkpoint=read(d/'checkpoint.json')
 if checkpoint.get('invalid',False) or checkpoint.get('valid') is False or not np.isfinite(checkpoint.get('loss',np.nan)):write(d/'outcome.json',dict(candidate=c,status='invalid_checkpoint'));return
 data=Data();value=evaluate(data,np.array(checkpoint['x']),c['alpha'])
 if value.get('invalid',False) or value.get('valid') is False or not np.isfinite(value.get('loss',np.nan)):write(d/'outcome.json',dict(candidate=c,status='invalid_final',evaluation=value));return
 status_path=Path(str(d/'checkpoint.json')+'.status.json');optimizer_status=read(status_path) if status_path.exists() else None
 evaluations=optimizer_status.get('evaluations') if optimizer_status is not None else checkpoint.get('evaluations')
 value.update(candidate=c,x=checkpoint['x'],fit_evaluations=evaluations,fit_evaluations_basis='optimizer_status' if optimizer_status is not None else 'checkpoint_lower_bound' if evaluations is not None else 'unavailable',optimizer_status_unavailable=optimizer_status is None);write(d/'final.json',value)
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
  before=time.monotonic();result['engine_status']='failed'
  try:
   with (sd/'engine.log').open('w') as log:
    done=subprocess.run([str(ENGINE),'PhysiCell_settings.xml'],cwd=case,stdout=log,stderr=subprocess.STDOUT,timeout=TIMEOUT,env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1'))
   result['engine_returncode']=done.returncode
   if done.returncode:result['error']=f'Engine returncode {done.returncode}'
   else:result['engine_status']='complete'
  except subprocess.TimeoutExpired as error:result.update(engine_status='timed_out',error=repr(error))
  except OSError as error:result['error']=repr(error)
  result['engine_seconds']=time.monotonic()-before;measurement=time.monotonic()
  arr,available,snapshots,parse_errors=support.measure_requested(case/'output',times,lambda path:transfer.snapshot(path,domain,shape,crop))
  lookup=np.asarray(slot['lookup'],int);row_available=available[lookup];indices=np.asarray(slot['indices'],int)
  np.savez_compressed(sd/'observables.npz',indices=indices[row_available],predicted=arr[lookup[row_available]],trajectory_predicted=arr,times_minutes=times,requested_indices=indices,requested_time_support=available)
  complete=bool(available.all()) and bool(np.isfinite(arr).all()) and result['engine_status']=='complete'
  result.update(status='complete' if complete else 'partial' if available.any() else 'failed',slot=slot,initialization=meta,snapshots=snapshots,snapshot_parse_errors=parse_errors,requested_snapshots=len(times),measured_snapshots=int(available.sum()),measurement_seconds=time.monotonic()-measurement,domain_size=domain,field_shape=shape,crop_origin=crop)
 except Exception as error:result.update(status='failed',error=repr(error),traceback=traceback.format_exc())
 result['wall_seconds']=time.monotonic()-started;write(sd/'outcome.json',result)


def _score_evidence(c):
 d=ROOT/'candidates'/c['id'];files={}
 for relative in ['final.json','slots.json','final_provenance.json','attempt_identity.json']:
  path=d/relative;files[relative]=support.file_sha(path) if path.exists() else None
 if (d/'slots.json').exists():
  for si,_ in enumerate(read(d/'slots.json')):
   for name in ['outcome.json','observables.npz']:
    relative=f'simulations/{si:03}/{name}';path=d/relative;files[relative]=support.file_sha(path) if path.exists() else None
 return dict(candidate=c,files=files)


def score_candidate(c):
 """Score one frozen candidate independently; always save its explicit outcome."""
 d=ROOT/'candidates'/c['id'];d.mkdir(parents=True,exist_ok=True);evidence=_score_evidence(c)
 result=dict(candidate=c,status='unavailable',ranking_score=None,ranking_basis='unavailable',score_evidence=evidence)
 if not (d/'final.json').exists():result['reason']='missing_final';write(d/'score.json',result);return result
 final=read(d/'final.json')
 if final.get('invalid',False) or final.get('valid') is False or not np.isfinite(final.get('loss',np.nan)):
  result.update(status='invalid',reason='invalid_final');write(d/'score.json',result);return result
 result.update(x=final['x'],count_offset=COUNT_OFFSET,approximation_data_loss=final['data_loss'],assumption_penalty=final['assumption_penalty'],ridge_penalty=final['ridge_penalty'],parameter_difference=final['parameter_difference'],search_objective=final['loss'])
 if not (d/'slots.json').exists():result['reason']='missing_slots';write(d/'score.json',result);return result
 data=Data();slots=read(d/'slots.json');pred=np.full((REPLICATES,data.n,30),np.nan);seen=np.zeros((REPLICATES,data.n),int);fail=[];completed=0
 for si,slot in enumerate(slots):
  sd=d/'simulations'/f'{si:03}';outcome=read(sd/'outcome.json') if (sd/'outcome.json').exists() else {}
  if outcome.get('status')!='complete':fail.append(dict(slot_index=si,status=outcome.get('status','missing'),reason=outcome.get('error')))
  else:completed+=1
  if not (sd/'observables.npz').exists():continue
  try:
   with np.load(sd/'observables.npz') as values:
    idx=values['indices'].astype(int);pp=values['predicted'];requested=np.asarray(slot['indices'],int)
    if pp.shape!=(len(idx),30) or not np.isin(idx,requested).all() or len(np.unique(idx))!=len(idx):raise ValueError('Native observation support differs from frozen slot')
    pred[slot['replicate'],idx]=pp;seen[slot['replicate'],idx]+=1
  except (ValueError,KeyError,OSError) as error:fail.append(dict(slot_index=si,status='invalid_observables',reason=repr(error)))
 reps=[];group_records=[]
 for rep in range(REPLICATES):
  q=support.score_support(pred[rep],data.obs,data.scales,data.weights,COEF,COUNT_OFFSET,fitting.composite_score,seen[rep]);gg={}
  for group in ['2N','4N']:
   weights=data.weights.copy();weights[data.groups!=group]=0;weights*=2
   gg[group]=support.score_support(pred[rep],data.obs,data.scales,weights,COEF,COUNT_OFFSET,fitting.composite_score,seen[rep])
  reps.append(dict(replicate=rep,data_loss=q['full_loss'],partial_data_loss=q['partial_loss'],ranking_data_loss=q['ranking_loss'],weighted_components=q['weighted_components'],native_support=q,group_losses={g:v['full_loss'] for g,v in gg.items()},partial_group_losses={g:v['partial_loss'] for g,v in gg.items()}));group_records.append(gg)
 usable=[q for q in reps if q['ranking_data_loss'] is not None];complete=all(q['data_loss'] is not None for q in reps)
 result.update(failed_slots=fail,completed_slots=completed,requested_slots=len(slots),replicates=reps,native_support=dict(replicates=[q['native_support'] for q in reps],complete=complete,supported_replicates=len(usable),requested_replicates=REPLICATES,weight_fraction=float(np.mean([q['native_support']['weight_fraction'] for q in reps]))))
 if usable:
  loss=float(np.mean([q['ranking_data_loss'] for q in usable]));sd=float(np.std([q['ranking_data_loss'] for q in usable],ddof=1)) if len(usable)>1 else 0. if complete else None;parts=np.mean([q['weighted_components'] for q in usable],axis=0).tolist()
  result.update(status='complete' if complete else 'partial',ranking_score=loss,ranking_penalized_score=loss+final['ridge_penalty'],ranking_basis='native_full' if complete else 'native_partial_normalized')
  if complete:
   result.update(simulator_data_loss=loss,simulator_data_loss_seed_sd=sd,simulator_penalized_loss=loss+final['ridge_penalty'],simulator_components=parts,group_losses={g:float(np.mean([q[g]['full_loss'] for q in group_records])) for g in ['2N','4N']})
  else:
   result.update(partial_simulator_data_loss=loss,partial_simulator_data_loss_seed_sd=sd,partial_simulator_penalized_loss=loss+final['ridge_penalty'],partial_simulator_components=parts,partial_group_losses={g:float(np.mean([q[g]['ranking_loss'] for q in group_records if q[g]['ranking_loss'] is not None])) if any(q[g]['ranking_loss'] is not None for q in group_records) else None for g in ['2N','4N']})
  # Never nanmean missing rows into apparently complete support.
  np.savez_compressed(d/'simulated.npz',predicted=pred.mean(axis=0),replicate_predicted=pred,seen=seen)
 result['ranking_evidence']=support.ranking_evidence(result)
 write(d/'score.json',result);return result


def score_candidate_worker(stage,index):
 c=candidate(stage,index)
 try:return score_candidate(c)
 except Exception as error:
  result=dict(candidate=c,status='unavailable',reason='candidate_scoring_failed',error=repr(error),traceback=traceback.format_exc(),ranking_score=None,ranking_basis='unavailable',score_evidence=_score_evidence(c))
  write(ROOT/'candidates'/c['id']/'score.json',result);return result


def _saved_score(c):
 path=ROOT/'candidates'/c['id']/'score.json'
 if not path.exists():return dict(candidate=c,status='unavailable',reason='missing_score_worker_record',ranking_score=None,ranking_basis='unavailable')
 result=read(path)
 if result.get('score_evidence')!=_score_evidence(c):raise ValueError('Candidate score frozen evidence mismatch: '+c['id'])
 if result.get('candidate')!=c:raise ValueError('Candidate score identity mismatch: '+c['id'])
 return result


def score(stage):
 """Deterministically reduce saved candidate records; never rerun scoring here."""
 candidates=read(ROOT/(stage+'_candidates.json'));results=[_saved_score(c) for c in candidates];write(ROOT/(stage+'_scores.json'),results)
 good=[v for v in results if v.get('ranking_score') is not None and np.isfinite(v['ranking_score'])]
 good.sort(key=support.ranking_key)
 if stage=='shared':
  if good:write(ROOT/'shared_best.json',good[0])
  else:write(ROOT/'shared_best.json',dict(status='unavailable',reason='no_finite_native_shared_parent',ranking_score=None,ranking_basis='unavailable'))
  return
 shared=read(ROOT/'shared_best.json') if (ROOT/'shared_best.json').exists() else dict(status='unavailable');pool=good+([shared] if shared.get('ranking_score') is not None else []);path=[];assigned=[]
 for alpha in ALPHAS:
  ranked=[]
  for value in pool:
   q=dict(value);penalty=alpha*value['parameter_difference'];q.update(evaluation_alpha=alpha,ridge_penalty=penalty,ranking_penalized_score=value['ranking_score']+penalty)
   q['simulator_penalized_loss' if value.get('ranking_basis')=='native_full' else 'partial_simulator_penalized_loss']=value['ranking_score']+penalty;ranked.append(q)
  ranked.sort(key=lambda value:support.ranking_key(value,value['ranking_penalized_score']));local=[v for v in ranked if v['candidate']['stage']=='shared' or v['candidate']['alpha']==alpha]
  path.append(dict(alpha=alpha,winner=ranked[0] if ranked else None,status='available' if ranked else 'unavailable'));assigned.append(dict(alpha=alpha,winner=local[0] if local else None,status='available' if local else 'unavailable'))
 write(ROOT/'results.json',dict(shared_best=shared,ridge_path=assigned,pooled_path=path,shared_candidates=read(ROOT/'shared_scores.json') if (ROOT/'shared_scores.json').exists() else [],ridge_candidates=results,parameter_names=PARAMETERS,natural_bounds=NATURAL_BOUNDS.tolist(),penalty='alpha * mean(((log(theta_2N)-log(theta_4N))/(log(upper)-log(lower)))^2)',count_offset='fixed common log1540000 field area; no fit calibration',replicates=REPLICATES))
