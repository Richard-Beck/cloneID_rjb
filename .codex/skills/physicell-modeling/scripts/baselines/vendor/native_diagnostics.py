"""Bounded parallel native screening and projection validation; no integer inheritance."""
from pathlib import Path
import csv,hashlib,json,os,sys,time,traceback
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from scipy.special import expit,xlogy,logsumexp
from scipy.linalg import cho_factor,cho_solve
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(HERE))
import perspective_model as a
import wgd_transfer as native
from wgd_colony import simulate_two_state

PY=a.PYTHON
BOOT=100
SEED=2610161900
EPS=1e-10
TIMEOUT=480



def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple,np.ndarray)):return [clean(v) for v in x]
 if isinstance(x,(np.integer,)):return int(x)
 if isinstance(x,(float,np.floating)):return float(x) if np.isfinite(x) else None
 return x

def read(p):return json.loads(Path(p).read_text())
def write(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);q=p.with_name(p.name+f'.{os.getpid()}.tmp');q.write_text(json.dumps(clean(x),indent=2,allow_nan=False)+'\n');q.replace(p)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def table(p,rows):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 keys=list(dict.fromkeys(k for r in rows for k in r))
 with p.open('w',newline='') as f:
  w=csv.DictWriter(f,keys);w.writeheader();w.writerows([clean(r) for r in rows])





def spec(final,s):
 nat=a.decode(final['x'],'no_wgd');o=s['oxygen'];dl=nat['dmax']*float(np.clip(1-o/20.5,0,1))
 return dict(p_low=a.state8(nat['low'],nat).tolist(),p_high=a.state8(nat['high'],nat).tolist(),rate_low=a.rate(nat['low'],o),rate_high=a.rate(nat['high'],o),initial_density=nat['rho0'],initial_high_fraction=s['initial_high_fraction'],cluster_size=nat['m0'],wgd_probability=0.,mitotic_death_low=dl,mitotic_death_high=nat['q']*dl,background_death_low_per_day=float(nat['low'][10]),background_death_high_per_day=float(nat['high'][10]),dead_duration_low_hours=float(nat['low'][11]),dead_duration_high_hours=float(nat['high'][11]),initial_dead_low_fraction=float(nat['low'][12]),initial_dead_high_fraction=float(nat['high'][12]),seed=s['seed'],times_days=s['times_days'],count_offset=a.B,domain_size=[1400*np.sqrt(1.5),1100*np.sqrt(1.5)],field_shape=[1100,1400],crop_origin=[-700,-550],mechanics_minutes=.5,phenotype_minutes=3.)

def run(stage,index):
 out=ROOT/stage;s=read(out/'slots.json')[index];folder=out/'cases'/s['candidate_id']/f'{index:05}';folder.mkdir(parents=True,exist_ok=True)
 if (folder/'outcome.json').exists():return
 started=time.monotonic();result=dict(status='failed',slot=s)
 try:
  fp=out/'frozen'/s['candidate_id']/'final.json';checkpoint_hash=sha(fp);assert checkpoint_hash==read(out/'parameter_manifest.json')[s['candidate_id']]
  final=read(fp);sp=spec(final,s);result['checkpoint_sha256']=checkpoint_hash
  remaining=stage_remaining_seconds(stage)
  if remaining<5:raise RuntimeError('Relative native-stage deadline exhausted; case not started')
  result['engine_timeout_seconds']=min(TIMEOUT,remaining)
  nativeout=native.execute(folder/'case',sp,timeout_seconds=min(TIMEOUT,remaining),measure=s['kind']=='main')
  if nativeout['status']!='success':raise RuntimeError(nativeout.get('error','engine failed'))
  tr=pd.read_csv(folder/'case/state_trajectory.csv');assert int(tr.wgd_events.max())==0
  result.update(status='complete',native=nativeout,initial_counts=tr.iloc[0].to_dict(),harvest_counts=tr.iloc[-1].to_dict())
  if s['kind']=='main':
   z=np.load(folder/'case/observables.npz');rows=a.Data().rows.iloc[s['observation_rows']];lookup=np.argmin(abs(z['times_minutes'][:,None]-rows.time_days.to_numpy()[None,:]*1440),axis=0)
   assert np.max(abs(z['times_minutes'][lookup]-rows.time_days.to_numpy()*1440),initial=0)<.500001
   np.savez_compressed(folder/'observables.npz',indices=s['observation_rows'],predicted=z['predicted'][lookup],trajectory_predicted=z['predicted'],times_minutes=z['times_minutes'])
 except Exception as e:result.update(error=repr(e),traceback=traceback.format_exc())
 result['wall_seconds']=time.monotonic()-started;write(folder/'outcome.json',result);print(index,s['candidate_id'],s['kind'],result['status'],result['wall_seconds'],flush=True)

def response(data,nat,o,f,horizon):
 f=float(np.clip(f,EPS,1-EPS));dt=data.dt[o];stop=np.ceil(horizon/dt)*dt;dl=nat['dmax']*float(np.clip(1-o/20.5,0,1))
 _,tr=simulate_two_state(a.state9(nat['low']),a.state9(nat['high']),a.rate(nat['low'],o),a.rate(nat['high'],o),nat['rho0'],nat['m0'],f,0.,dl,nat['q']*dl,np.array([0.,stop]),dt=dt,observation_area=a.AREA)
 if not np.isfinite(tr[:,:3]).all() or not (tr[:,1:3]>0).all():raise RuntimeError('Invalid two-state internal response')
 gain=np.log(tr[:,2]/tr[0,2])-np.log(tr[:,1]/tr[0,1])
 if nat['dmax']==0 and np.array_equal(nat['low'],nat['high']):gain[:]=0.
 return dict(t=tr[:,0],low=tr[:,1],high=tr[:,2],gain=gain)

def nb_modes(n,h,logg,t,weights,prior,kappa=1.,precision=.25):
 n=np.asarray(n);h=np.asarray(h);t=np.asarray(t);weights=np.atleast_2d(weights)*(n>0)[None,:]
 if np.any(h[n==0]!=0):raise RuntimeError('State appeared without founders')
 r=np.maximum(n,1)/kappa;lm=np.log(np.maximum(n,1))+logg;lr=np.log(r);lo=np.full(len(weights),prior-25.);hi=np.full(len(weights),prior+25.)
 for _ in range(40):
  rate=(lo+hi)/2;p=expit(lm[None,:]+rate[:,None]*t[None,:]-lr[None,:]);g=(weights*t[None,:]*((h+r)[None,:]*p-h[None,:])).sum(axis=1)+precision*(rate-prior);lo=np.where(g<0,rate,lo);hi=np.where(g>=0,rate,hi)
 rate=(lo+hi)/2;p=expit(lm[None,:]+rate[:,None]*t[None,:]-lr[None,:]);curv=(weights*t[None,:]**2*(h+r)[None,:]*p*(1-p)).sum(axis=1)+precision
 return rate,1/curv

def analyze(stage,index):
 started=time.monotonic();out=ROOT/stage;selected=read(out/'candidates.json');c=selected[index];cid=c['id'];folder=out/'frozen'/cid;final=read(folder/'final.json');nat=a.decode(final['x'],'no_wgd');data=a.Data();dest=out/'analysis'/cid;dest.mkdir(parents=True,exist_ok=True)
 slots=[s for s in read(out/'slots.json') if s['candidate_id']==cid]
 reps=read(out/'contract.json')['replicates'];pred=np.full((reps,data.n,30),np.nan);seen=np.zeros((reps,data.n),int);cases=[];raw=[];failed=[]
 for s in slots:
  sd=out/'cases'/cid/f"{s['case_index']:05}";p=sd/'outcome.json'
  if not p.exists():failed.append(dict(case_index=s['case_index'],reason='missing'));continue
  result=read(p)
  if result['status']!='complete':failed.append(dict(case_index=s['case_index'],reason=result.get('error','failed')));continue
  tr=pd.read_csv(sd/'case/state_trajectory.csv');n=tr.iloc[0][['n_low','n_high']].to_numpy(float);h=tr.iloc[-1][['n_low','n_high']].to_numpy(float);cases.append(dict(slot=s,tr=tr,n=n))
  raw.append(dict(candidate_id=cid,case_index=s['case_index'],kind=s['kind'],episode_id=s['episode_id'],oxygen=s['oxygen'],seed_low=n[0],seed_high=n[1],harvest_low=h[0],harvest_high=h[1],absent_seed_state=bool((n==0).any()),local_extinction=bool(((n>0)&(h==0)).any())))
  if s['kind']=='main':
   z=np.load(sd/'observables.npz');ix=z['indices'].astype(int);pred[s['replicate'],ix]=z['predicted'];seen[s['replicate'],ix]+=1
 table(dest/'native_counts.csv',raw)
 ix=np.array(sorted({int(j) for s in slots if s['kind']=='main' for j in s['observation_rows']}),int);weights=data.weights[ix].copy()
 # Rebalance screened support within founder, same episode and row hierarchy.
 if stage=='screen':
  for g in ['2N','4N']:
   mask=data.rows.iloc[ix].group.to_numpy()==g
   for j in range(6):weights[mask,j]*=.5/weights[mask,j].sum()
 parts=[]
 for pp in pred:
  if len(ix) and np.isfinite(pp[ix]).all():parts.append(a.fitting.composite_score(pp[ix],data.obs[ix],data.scales[ix],weights,a.COEF,offset=a.B)[2].tolist())
  else:parts.append([None]*6)
 microscopy=dict(indices=ix.tolist(),observations=len(ix),requested_observations=len(ix),completed_observations_all_replicates=int(np.sum(np.all(seen[:,ix]==1,axis=0))),replicate_components=parts,weighted_components=[float(np.mean([p[j] for p in parts])) if all(p[j] is not None for p in parts) else None for j in range(6)],required_nonfinite_values=int((~np.isfinite(pred[:,ix])).sum()),all_observations_seen_once=bool((seen[:,ix]==1).all()) if len(ix) else False)
 microscopy['total']=sum(microscopy['weighted_components']) if all(v is not None for v in microscopy['weighted_components']) else None
 if stage=='screen':
  av=a.evaluate(data,np.array(final['x']),c['alpha'],'no_wgd',dest/'cohort_reference')
  if av.get('valid'):
   ap=np.load(dest/'cohort_reference'/'approximation.npz')['predicted']
   microscopy['approximation_matched_support_loss']=a.fitting.composite_score(ap[ix],data.obs[ix],data.scales[ix],weights,a.COEF,offset=a.B)[0]
   microscopy['native_minus_approximation_bias']=None if microscopy['total'] is None else microscopy['total']-microscopy['approximation_matched_support_loss']
 write(dest/'microscopy_scores.json',microscopy);np.savez_compressed(dest/'microscopy.npz',observed=data.obs,predicted=pred,weights=data.weights,scales=data.scales,seen=seen,indices=ix,screen_weights=weights)
 rng=np.random.default_rng(SEED+index+(5000 if stage!='screen' else 0));cache={};endcache={};by={p['episode_id']:i for i,p in enumerate(data.episodes)}
 olddelta=final.get('native_correction',np.zeros(len(data.episodes)))
 if isinstance(olddelta,dict):olddelta=olddelta.get('delta_per_day',np.zeros(len(data.episodes)))
 olddelta=np.array(olddelta,float)
 if stage=='screen':frozen_npz_path=dest/'cohort_reference'/'approximation.npz'
 else:
  a.evaluate(data,np.array(final['x']),c['alpha'],'no_wgd',dest/'frozen_cohort',correction=dict(episode_ids=[p['episode_id'] for p in data.episodes],delta_per_day=olddelta.tolist()))
  frozen_npz_path=dest/'frozen_cohort'/'approximation.npz'
 frozen_arrays=np.load(frozen_npz_path) if frozen_npz_path.exists() else None
 frozen_assays={q['id']:q for q in final.get('assays',[])}
 def frozen_z_at(i,t,fallback):
  if frozen_arrays is not None and 'latent_'+str(i) in frozen_arrays.files:return float(np.interp(t,frozen_arrays['trace_'+str(i)][:,0],frozen_arrays['latent_'+str(i)]))
  return fallback
 def resp(o,f,h):
  key=(o,float(f),float(h))
  if key not in cache:cache[key]=response(data,nat,*key)
  return cache[key]
 # Shared resampling weights prevent repeated probe endpoints from pretending to
 # be independent information across passages.
 bootweights={}
 for o in data.dt:
  for f in PROBE_FRACTIONS:
   ss=[q for q in cases if q['slot']['kind']=='minority_probe' and q['slot']['oxygen']==o and q['slot']['initial_high_fraction']==f]
   if ss:
    bw=rng.multinomial(len(ss),np.full(len(ss),1/len(ss)),size=BOOT)
    for j,q in enumerate(ss):bootweights[q['slot']['case_index']]=bw[:,j]
 def endpoint(q,t,weight):
  si=q['slot']['case_index'];key=(si,t)
  if key not in endcache:
   tr=q['tr'];j=int(np.argmin(abs(tr.time_minutes.to_numpy()-t*1440)));actual=float(tr.time_minutes.iloc[j]/1440)
   if abs(actual-t)>.500001/1440:return None
   n=q['n'];h=tr.iloc[j][['n_low','n_high']].to_numpy(float);f=float(n[1]/max(n.sum(),1));r=resp(q['slot']['oxygen'],f,float(tr.time_minutes.iloc[-1]/1440));g=np.log([np.interp(actual,r['t'],r['low'])/r['low'][0],np.interp(actual,r['t'],r['high'])/r['high'][0]])
   endcache[key]=dict(n=n,h=h,g=g,t=actual,case_index=si,kind=q['slot']['kind'],fraction=q['slot']['initial_high_fraction'])
  return dict(endcache[key],weight=weight)
 measurements=[];rawdelta=[];variances=[];bootraw=[];references=[];sensraw={'one_percent':[],'five_percent':[]}
 for ei,p in enumerate(data.episodes):
  eid=p['episode_id'];f=final['seed_fractions'][eid];duration=p['duration_days'];records=[]
  rr=resp(p['oxygen'],f,max([duration]+p['needed_times_days']));references.append(rr)
  mains=[q for q in cases if q['slot']['kind']=='main' and q['slot']['episode_id']==eid]
  for q in mains:
   e=endpoint(q,duration,1.)
   if e:records.append(e)
  # Unsampled screen passages borrow same-oxygen main windows of comparable
  # composition; their horizon snapshots are not fabricated.
  if not mains and stage=='screen':
   ps=[q for q in cases if q['slot']['kind']=='main' and q['slot']['oxygen']==p['oxygen'] and q['slot']['founding_group']==p['founding_group']]
   for q in ps:
    t=float(q['tr'].time_minutes.iloc[-1]/1440);distance=abs(float(q['slot']['initial_high_fraction'])-f);e=endpoint(q,t,1/(1+(distance/.15)**2))
    if e:records.append(e)
  if f<=.1 or f>=.9:
   ff=[.01,.05] if f<=.1 else [.95,.99]
   for q in cases:
    s=q['slot']
    if s['kind']=='minority_probe' and s['oxygen']==p['oxygen'] and s['initial_high_fraction'] in ff:
     e=endpoint(q,duration,1/(1+((s['initial_high_fraction']-f)/.05)**2))
     if e:records.append(e)
  if records:
   n=np.array([q['n'] for q in records]);h=np.array([q['h'] for q in records]);g=np.array([q['g'] for q in records]);ts=np.array([q['t'] for q in records]);w=np.array([q['weight'] for q in records]);bw=[]
   # Main observations independent by field, probes share bootstrap across episodes.
   for q in records:bw.append(bootweights.get(q['case_index'],rng.poisson(1,BOOT)))
   ww=np.vstack([np.ones(len(records)),np.array(bw).T])*w[None,:];modes=[];vs=[]
   for state,sgn in enumerate([-1,1]):
    mode,var=nb_modes(n[:,state],h[:,state],g[:,state],ts,ww,sgn*olddelta[ei]/2);modes.append(mode);vs.append(var)
   dr=modes[1]-modes[0];vr=float(vs[1][0]+vs[0][0]);rawdelta.append(dr[0]);variances.append(vr);bootraw.append(dr[1:])
   for name,allowed in [('one_percent',[.01,.99]),('five_percent',[.05,.95])]:
    mask=np.array([q['kind']=='main' or q['fraction'] in allowed for q in records]);mm=[]
    for state,sgn in enumerate([-1,1]):mm.append(nb_modes(n[:,state],h[:,state],g[:,state],ts,w*mask,sgn*olddelta[ei]/2)[0][0])
    sensraw[name].append(mm[1]-mm[0])
  else:
   rawdelta.append(olddelta[ei]);variances.append(8.);bootraw.append(np.full(BOOT,olddelta[ei]));sensraw['one_percent'].append(olddelta[ei]);sensraw['five_percent'].append(olddelta[ei])
  measurements.append(dict(candidate_id=cid,episode_id=eid,episode_index=ei,founding_group=p['founding_group'],arm=p['arm'],oxygen=p['oxygen'],duration_days=duration,frozen_seed_fraction=f,main_fields=len(mains),native_records=len(records),old_correction_per_day=olddelta[ei],native_raw_correction_per_day=rawdelta[-1],raw_correction_sd=np.sqrt(variances[-1]),cohort_selection_per_day=float(np.interp(duration,rr['t'],rr['gain'])/duration)))
 n=len(data.episodes);L=np.zeros((n,n));edges=[]
 for i,p in enumerate(data.episodes):
  par=p['parent_episode_id']
  if par is not None:
   j=by[par]
   if p['oxygen']==data.episodes[j]['oxygen']:
    L[i,i]+=1;L[j,j]+=1;L[i,j]-=1;L[j,i]-=1;edges.append([i,j])
  # Matching oxygen and longitudinal position across O1/O2 smooths within founder.
  if p['arm']=='O1':
   other=p['episode_id'].replace('_O1_','_O2_')
   if other in by and data.episodes[by[other]]['oxygen']==p['oxygen']:
    j=by[other];L[i,i]+=1;L[j,j]+=1;L[i,j]-=1;L[j,i]-=1;edges.append([i,j])
 precision=1/np.array(variances);lam=1.;ridge=.1;factor=cho_factor(np.diag(precision+ridge)+lam*L)
 def smooth(v):return cho_solve(factor,precision[:,None]*np.array(v).reshape(n,-1)+ridge*olddelta[:,None])
 delta=smooth(rawdelta)[:,0];db=smooth(np.vstack(bootraw));ds={k:smooth(v)[:,0] for k,v in sensraw.items()}
 neutral=nat['dmax']==0 and np.array_equal(nat['low'],nat['high'])
 if neutral:
  delta[:]=0.;db[:]=0.
  for v in ds.values():v[:]=0.
 correction=dict(exact_neutral_state_invariant=bool(neutral),episode_ids=[p['episode_id'] for p in data.episodes],delta_per_day=delta.tolist(),source_x=final['x'],source_sha256=sha(folder/'final.json'),lambda_smooth=lam,ridge=ridge,negative_binomial_kappa=1.,weak_rate_prior_sd=2.,local_zero_counts_retained=True,chromosome_assays_used=False,bootstrap_replicates=BOOT,graph_edges=edges)
 write(dest/'correction.json',correction)
 if stage=='screen':
  cv=a.evaluate(data,np.array(final['x']),c['alpha'],'no_wgd',dest/'native_corrected_cohort',correction=correction)
  cv.update(x=final['x'],alpha=c['alpha'],native_correction=correction,candidate_id=cid)
  write(dest/'corrected_final.json',cv)
 np.savez_compressed(dest/'selection_bootstrap.npz',delta=db)
 for i,r in enumerate(measurements):r['smoothed_correction_per_day']=delta[i]
 table(dest/'selection.csv',measurements)
 states={};oldstates={};starts={};trajectory=[];assays=[];curves={f'{g}_{arm}':[] for g in ['2N','4N'] for arm in ['C','O1','O2']};maxshift=0;max_frozen_seed_error=0.
 for i,p in enumerate(data.episodes):
  eid=p['episode_id'];par=p['parent_episode_id'];rr=references[i]
  if par is None:
   ff=nat['founder_high'][p['founding_group']];z=float(np.log(ff)-np.log1p(-ff));zb=np.full(BOOT,z);zo=z;zs={k:z for k in ds};starts[eid]=0.
  else:
   j=by[par];t=p['parent_transfer_time_days'];pr=references[j];gain=float(np.interp(t,pr['t'],pr['gain']));ps=states[par];z=ps['z']+gain+delta[j]*t;zb=ps['zb']+gain+db[j]*t;zo=oldstates[par]+gain+olddelta[j]*t;zs={k:ps['zs'][k]+gain+ds[k][j]*t for k in ds};starts[eid]=starts[par]+t
  max_frozen_seed_error=max(max_frozen_seed_error,abs(float(expit(zo))-float(final['seed_fractions'][eid])))
  states[eid]=dict(z=z,zb=zb,zs=zs);oldstates[eid]=zo
  times=sorted(set([0.,p['duration_days']]+p['needed_times_days']+[q['time_days'] for q in data.assays if q['episode_id']==eid]))
  for t in times:
   gain=float(np.interp(t,rr['t'],rr['gain']));zz=z+gain+delta[i]*t;oldz=frozen_z_at(i,t,zo+gain+olddelta[i]*t);draw=zb+gain+db[i]*t;lo,hi=expit(np.quantile(draw,[.025,.975]));newf=float(expit(zz));oldf=float(expit(oldz));maxshift=max(maxshift,abs(newf-oldf));sens={k:float(expit(zs[k]+gain+ds[k][i]*t)) for k in ds}
   row=dict(candidate_id=cid,episode_id=eid,founding_group=p['founding_group'],arm=p['arm'],oxygen=p['oxygen'],time_days=t,culture_day=starts[eid]+t,frozen_fraction=oldf,checked_fraction=newf,checked_log_odds=zz,bootstrap_lower=lo,bootstrap_upper=hi,**{k+'_fraction':v for k,v in sens.items()});trajectory.append(row)
   item=dict(x=row['culture_day'],frozen=oldf,checked=newf,lo=lo,hi=hi,episode=eid,local_day=t,**sens)
   for arm in ['C','O1','O2'] if p['arm']=='common' else [p['arm']]:curves[f"{p['founding_group']}_{arm}"].append(item)
  for q in data.assays:
   if q['episode_id']!=eid:continue
   t=q['time_days'];gain=float(np.interp(t,rr['t'],rr['gain']));zz=z+gain+delta[i]*t;draw=zb+gain+db[i]*t;k=q['k'];nn=q['n'];sat=xlogy(k,k/nn)+xlogy(nn-k,1-k/nn);dev=2*(sat+k*np.logaddexp(0,-zz)+(nn-k)*np.logaddexp(0,zz));lp=logsumexp(-k*np.logaddexp(0,-draw)-(nn-k)*np.logaddexp(0,draw))-np.log(BOOT);lo,hi=expit(np.quantile(draw,[.025,.975]));assays.append(dict(candidate_id=cid,assay_id=q['id'],episode_id=eid,founding_group=p['founding_group'],arm=p['arm'],culture_day=starts[eid]+t,k=k,n=nn,observed_fraction=k/nn,frozen_fraction=float(frozen_assays[q['id']]['predicted_high']) if q['id'] in frozen_assays else float(expit(frozen_z_at(i,t,zo+gain+olddelta[i]*t))),checked_fraction=float(expit(zz)),bootstrap_lower=lo,bootstrap_upper=hi,deviance=float(dev),bootstrap_marginal_deviance=float(2*(sat-lp))))
 table(dest/'trajectories.csv',trajectory);table(dest/'assays.csv',assays)
 micro={f'{g}_{arm}':[] for g in ['2N','4N'] for arm in ['C','O1','O2']}
 def display(v):return [np.expm1(v[0]),np.expm1(v[1]),v[2],np.exp(v[3]),v[4],*np.exp(v[[7,17,27]])]
 for j,row in data.rows.iterrows():
  if not seen[:,j].any():continue
  p=data.byid[row.episode_id];item=dict(x=starts[row.episode_id]+row.time_days,episode=row.episode_id,passage=row.passage_id,observed=display(data.obs[j]),native=[display(pp[j]) for pp in pred])
  for arm in ['C','O1','O2'] if p['arm']=='common' else [p['arm']]:micro[f"{p['founding_group']}_{arm}"].append(item)
 for values in list(curves.values())+list(micro.values()):values.sort(key=lambda r:r['x'])
 difference=float(np.mean(((np.array(final['x'])[7:20]-np.array(final['x'])[20:33])/np.log(1.5))**2));assayloss=float(np.mean([q['deviance'] for q in assays]));marginal=float(np.mean([q['bootstrap_marginal_deviance'] for q in assays]));score=None if microscopy['total'] is None else microscopy['total']+assayloss+c['alpha']*difference
 summary=dict(candidate_id=cid,alpha=c['alpha'],main_complete=sum(r['kind']=='main' for r in raw),main_requested=sum(s['kind']=='main' for s in slots),probes_complete=sum(r['kind']=='minority_probe' for r in raw),probes_requested=sum(s['kind']=='minority_probe' for s in slots),failures=failed,main_absent_seed_fields=sum(r['kind']=='main' and r['absent_seed_state'] for r in raw),main_local_harvest_extinctions=sum(r['kind']=='main' and r['local_extinction'] for r in raw),mean_assay_deviance=assayloss,mean_bootstrap_marginal_assay_deviance=marginal,native_microscopy_loss=microscopy['total'],ridge_penalty=c['alpha']*difference,joint_score=score,max_fraction_change=maxshift,max_frozen_seed_fraction_replay_error=max_frozen_seed_error,probe_one_vs_five_max_fraction_difference=max(abs(r['one_percent_fraction']-r['five_percent_fraction']) for r in trajectory),selection_mean_abs_error_per_day=float(np.mean(abs(delta-olddelta))),selection_rmse_per_day=float(np.sqrt(np.mean((delta-olddelta)**2))),physical_parameters_unchanged=True,frozen_assay_source='Exact saved adapter final.json assay predictions',frozen_curve_source='Exact recomputed adapter latent_i arrays; source physical vector and frozen correction',checkpoint_sha256=sha(folder/'final.json'),chromosome_fitted=False,finite_latent_log_states=all(np.isfinite(r['checked_log_odds']) for r in trajectory),elapsed_seconds=time.monotonic()-started)
 write(dest/'summary.json',summary);write(dest/'report_data.json',dict(id=cid,summary=summary,microscopy_scores=microscopy,curves=curves,assays=assays,microscopy=micro,selection=measurements));print(cid,clean(summary),flush=True)


PROBE_FRACTIONS=[.01,.05,.95,.99]
def stage_remaining_seconds(stage):
 identity=read(ROOT/stage/"stage_identity.json")
 deadline=identity.get("deadline_unix")
 return max(0.,deadline-time.time()) if deadline is not None else TIMEOUT
