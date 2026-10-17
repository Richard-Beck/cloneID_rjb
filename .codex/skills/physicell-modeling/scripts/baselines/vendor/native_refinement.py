"""Bounded native-corrected local updates; fresh final native checks are required."""
from pathlib import Path
import argparse,os,time,json,signal,traceback
import numpy as np
from scipy.special import logit,expit
from scipy.optimize import brentq
import perspective_model as a
import perspective_search as e
r=a.ROOT
SECONDS=100.
def run(index,seconds=SECONDS,replicate=0):
 if isinstance(replicate,bool) or not isinstance(replicate,(int,np.integer)) or replicate<0:raise ValueError('Invalid refinement replicate')
 cs=a.read(r/'screen_candidates.json');c=cs[index];cid=c['id'];source_path=r/'candidates'/cid/'final.json'
 candidate_id=f'refined_{cid}_r{replicate:03}';folder=r/'refinement'/cid/f'replicate_{replicate:03}'
 if folder.exists():raise RuntimeError('Refinement attempt exists; automatic overwrite/retry prohibited')
 if not source_path.exists():
  a.write(folder/'outcome.json',dict(status='skipped_missing_source'));return
 source=a.read(source_path)
 if source.get('valid') is False or source.get('invalid',False) or not np.isfinite(source.get('loss',np.nan)):
  a.write(folder/'outcome.json',dict(status='skipped_invalid_source'));return
 if cid.startswith('anchor_'):
  a.write(folder/'outcome.json',dict(status='retained_immutable_anchor',source=str(r/'candidates'/cid/'final.json')));return
 summary_path=r/'screen/analysis'/cid/'summary.json'
 summary=a.read(summary_path) if summary_path.exists() else {}
 cp=r/'screen/analysis'/cid/'correction.json'
 if summary.get('correction_status')=='unavailable' or not cp.exists():
  a.write(folder/'outcome.json',dict(status='skipped_unavailable_native_correction',failures=summary.get('failures',[]),reason=summary.get('correction_reason')));return
 correction=a.read(cp)
 if correction.get('status')=='unavailable' or correction.get('native_records',1)<=0:
  a.write(folder/'outcome.json',dict(status='skipped_unsupported_native_correction'));return
 microscopy_path=r/'screen/analysis'/cid/'microscopy_scores.json'
 if not microscopy_path.exists():
  a.write(folder/'outcome.json',dict(status='skipped_missing_native_microscopy'));return
 microscopy=a.read(microscopy_path)
 bias_value=microscopy.get('ranking_native_minus_approximation_bias',microscopy.get('native_minus_approximation_bias'))
 if bias_value is None or not np.isfinite(float(bias_value)):
  a.write(folder/'outcome.json',dict(status='skipped_invalid_native_microscopy',microscopy=microscopy));return
 fixed_native_bias=float(bias_value)
 source_x=np.asarray(source['x'],float)
 assert np.max(abs(source_x-np.asarray(correction['source_x'])))<1e-12,'Correction x mismatch'
 import hashlib
 assert correction.get('source_sha256')==hashlib.sha256((r/'screen/frozen'/cid/'final.json').read_bytes()).hexdigest(),'Correction source hash mismatch'
 assert source_x.shape==(33,) and np.isfinite(source_x).all(),'Invalid refinement source vector'
 source_final_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest();correction_sha256=hashlib.sha256(cp.read_bytes()).hexdigest()
 folder.mkdir(parents=True,exist_ok=True)
 data=a.Data();refinement_seed=int(c['seed']+900000+1000003*replicate);rng=np.random.default_rng(refinement_seed)
 started=time.monotonic();deadline=started+seconds;calls=0;accept=0
 z=e.encode(source_x);source_z=z.copy();active=e.ACTIVE.copy();width=e.WIDTH[active]
 # Maximum local movement: .08 biology log-units; founder shift <=3 log-odds and .05 fraction.
 radius=np.r_[np.full(2,3/(2*e.L)),.04,.06,np.full(28,.08)/e.WIDTH[5:]]
 assert radius.shape==(32,)
 lo=np.maximum(0,z-radius);hi=np.minimum(1,z+radius);center=z.copy()
 founder_low=np.clip(source_x[:2]-.05,e.EPS,1-e.EPS);founder_high=np.clip(source_x[:2]+.05,e.EPS,1-e.EPS)
 lo[:2]=np.maximum(lo[:2],(logit(founder_low)+e.L)/(2*e.L));hi[:2]=np.minimum(hi[:2],(logit(founder_high)+e.L)/(2*e.L))
 if replicate:
  # Independent starts explore only the same source-anchored bounded region.
  z=lo+rng.random(len(lo))*(hi-lo)
 a.write(folder/'attempt_identity.json',dict(candidate_id=candidate_id,source_candidate_id=cid,refinement_replicate=int(replicate),refinement_seed=refinement_seed,source_final_sha256=source_final_sha256,correction_sha256=correction_sha256,source_x=source_x.tolist(),source_z=source_z.tolist(),lower_z=lo.tolist(),upper_z=hi.tolist(),initial_z=z.tolist(),requested_threads=1,optimizer_seconds=seconds))
 step=.5*radius
 class Budget(Exception):pass
 def stop(signum,frame):raise Budget()
 signal.signal(signal.SIGTERM,stop)
 records=[]
 def objective(zz,label):
  nonlocal calls
  if calls and time.monotonic()>deadline:raise Budget()
  xx=e.decode(zz);v=a.evaluate(data,xx,c['alpha'],'no_wgd',correction=correction);calls+=1
  records.append(dict(evaluation=calls,label=label,loss=v['loss'],data_loss=v.get('data_loss'),assay_deviance=v.get('assay_deviance'),elapsed_seconds=time.monotonic()-started))
  return dict(v,x=xx.tolist())
 best=objective(z,'source_native_corrected' if replicate==0 else 'independent_source_trust_region_start');initial=best.copy();bestz=z.copy();a.write(folder/'initial.json',a.clean(initial));sweep=0
 if not best.get('valid') or not np.isfinite(best.get('loss',np.nan)):
  a.write(folder/'outcome.json',dict(status='skipped_invalid_corrected_source',details=a.clean(best)));return
 def packed(value,complete=False):
  value=dict(value)
  value.update(candidate=dict(c,id=candidate_id,parent_candidate_id=cid,origin='Native-corrected bounded local refinement',refinement_replicate=int(replicate)),native_support_basis=microscopy.get('ranking_basis','native_full'),native_support=microscopy.get('native_support'),native_parent_failures=summary.get('failures',[]),refinement_replicate=int(replicate),refinement_seed=refinement_seed,source_final_sha256=source_final_sha256,correction_sha256=correction_sha256,source_candidate_id=cid,status='native_corrected_approximation',correction_path=str(cp.relative_to(r)),source_x=source_x.tolist(),evaluations=calls,accepted_moves=accept,elapsed_seconds=time.monotonic()-started,trust_region=dict(anchor='original source physical vector',source_z=source_z.tolist(),lower_z=lo.tolist(),upper_z=hi.tolist(),initial_z=z.tolist(),max_log_biology_change=.08,max_founder_logodds_change=3.,max_absolute_founder_fraction_change=.05,max_dmax_change=.04,max_q_change=.06),initial_corrected_loss=initial['loss'],source_corrected_loss=initial['loss'] if replicate==0 else None,fixed_native_microscopy_bias=fixed_native_bias,native_corrected_comparison_loss=value['data_loss']+fixed_native_bias+value['assay_deviance']+value['ridge_penalty'],native_corrected_microscopy_estimate=value['data_loss']+fixed_native_bias)
  value.update(optimization_complete=bool(complete),checkpoint_recovery_available=True,requested_threads=1)
  return value
 a.write(folder/'checkpoint.json',a.clean(packed(best)))
 # Cheap conditional founder profile holding native-corrected growth gains fixed,
 # followed by a complete new coupled cohort evaluation before accepting it.
 try:
  proposed=bestz.copy()
  for j,group in enumerate(['2N','4N']):
   qs=[q for q in initial['assays'] if data.byid[q['episode_id']]['founding_group']==group]
   root_logodds=float(logit(source_x[j] if replicate==0 else initial['x'][j]));b=np.array([q['log_odds']-root_logodds for q in qs]);nn=np.array([q['n'] for q in qs]);kk=sum(q['k'] for q in qs)
   left=2*e.L*lo[j]-e.L;right=2*e.L*hi[j]-e.L
   def derivative(value):return float(np.sum(nn*expit(value+b))-kk)
   target=left if derivative(left)>=0 else right if derivative(right)<=0 else brentq(derivative,left,right)
   proposed[j]=(target+e.L)/(2*e.L)
  profile=objective(proposed,'conditional_founder_profile_full_recheck')
  if profile.get('valid') and np.isfinite(profile.get('loss',np.nan)) and profile['loss']<best['loss']-1e-9:
   best=profile;bestz=proposed;accept+=1;a.write(folder/'checkpoint.json',a.clean(packed(best)))
 except Budget:pass

 try:
  while time.monotonic()<deadline:
   sweep+=1;before=accept
   # Preserve shared means while testing the growth/death selection contrasts first.
   directions=[]
   for j in [9,10,6,7,8]:
    d=np.zeros(32);d[int(np.where(active==7+j)[0][0])]=1.;d[int(np.where(active==20+j)[0][0])]=-1.
    directions.append(('state_contrast_'+a.NAMES[j],d))
   priorities=[0,1]+[int(np.where(active==j)[0][0]) for j in [3,4,5,16,29,17,30]]
   remaining=[j for j in rng.permutation(32) if j not in priorities]
   for k in priorities+remaining:
    d=np.zeros(32);d[k]=1.;directions.append(('coordinate_'+a.PARAMETERS[active[k]],d))
   for label,direction in directions:
    sign=1 if rng.random()<.5 else -1
    zz=np.clip(bestz+sign*step*direction,lo,hi)
    if np.array_equal(zz,bestz):zz=np.clip(bestz-sign*step*direction,lo,hi)
    if np.array_equal(zz,bestz):continue
    value=objective(zz,label)
    if value.get('valid') and np.isfinite(value.get('loss',np.nan)) and value['loss']<best['loss']-1e-9:
     best=value;bestz=zz;accept+=1;a.write(folder/'checkpoint.json',a.clean(packed(best)))
   if accept==before:step*=.5
 except Budget:pass
 # Retain source when every local proposal fails.
 best=packed(best,complete=True)
 a.write(folder/'final.json',a.clean(best));a.write(folder/'trials.json',a.clean(records))
 # Native agent consumes refined_<source> as a distinct candidate.
 out=r/'candidates'/candidate_id;out.mkdir(parents=True,exist_ok=True)
 a.write(out/'final.json',a.clean(best))
 print(cid,'refinement',replicate,calls,accept,best['loss'],flush=True)
