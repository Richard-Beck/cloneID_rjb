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
def run(index,seconds=SECONDS):
 cs=a.read(r/'screen_candidates.json');c=cs[index];cid=c['id'];source=a.read(r/'candidates'/cid/'final.json')
 if cid.startswith('anchor_'):
  a.write(r/'refinement'/cid/'outcome.json',dict(status='retained_immutable_anchor',source=str(r/'candidates'/cid/'final.json')));return
 summary=a.read(r/'screen/analysis'/cid/'summary.json')
 if summary.get('failures'):
  a.write(r/'refinement'/cid/'outcome.json',dict(status='skipped_incomplete_native_parent',failures=summary['failures']));return
 cp=r/'screen/analysis'/cid/'correction.json'
 correction=a.read(cp)
 microscopy_path=r/'screen/analysis'/cid/'microscopy_scores.json'
 microscopy=a.read(microscopy_path)
 bias_value=microscopy.get('native_minus_approximation_bias')
 if bias_value is None or not np.isfinite(float(bias_value)):
  a.write(r/'refinement'/cid/'outcome.json',dict(status='skipped_invalid_native_microscopy',microscopy=microscopy));return
 fixed_native_bias=float(bias_value)
 source_x=np.asarray(source['x'],float)
 assert np.max(abs(source_x-np.asarray(correction['source_x'])))<1e-12,'Correction x mismatch'
 folder=r/'refinement'/cid;folder.mkdir(parents=True,exist_ok=True)
 data=a.Data();rng=np.random.default_rng(c['seed']+900000)
 started=time.monotonic();deadline=started+seconds;calls=0;accept=0
 z=e.encode(source_x);active=e.ACTIVE.copy();width=e.WIDTH[active]
 # Maximum local movement: .08 biology log-units; founder shift <=3 log-odds and .05 fraction.
 radius=np.r_[np.full(2,3/(2*e.L)),.04,.06,np.full(28,.08)/e.WIDTH[5:]]
 assert radius.shape==(32,)
 lo=np.maximum(0,z-radius);hi=np.minimum(1,z+radius);center=z.copy()
 founder_low=np.clip(source_x[:2]-.05,e.EPS,1-e.EPS);founder_high=np.clip(source_x[:2]+.05,e.EPS,1-e.EPS)
 lo[:2]=np.maximum(lo[:2],(logit(founder_low)+e.L)/(2*e.L));hi[:2]=np.minimum(hi[:2],(logit(founder_high)+e.L)/(2*e.L))
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
 best=objective(z,'source_native_corrected');initial=best.copy();bestz=z.copy();a.write(folder/'initial.json',a.clean(initial));sweep=0
 if not best.get('valid') or best['loss']>=1e24:
  a.write(folder/'outcome.json',dict(status='skipped_invalid_corrected_source',details=a.clean(best)));return
 # Cheap conditional founder profile holding native-corrected growth gains fixed,
 # followed by a complete new coupled cohort evaluation before accepting it.
 proposed=bestz.copy()
 for j,group in enumerate(['2N','4N']):
  qs=[q for q in initial['assays'] if data.byid[q['episode_id']]['founding_group']==group]
  root_logodds=float(logit(source_x[j]));b=np.array([q['log_odds']-root_logodds for q in qs]);nn=np.array([q['n'] for q in qs]);kk=sum(q['k'] for q in qs)
  left=2*e.L*lo[j]-e.L;right=2*e.L*hi[j]-e.L
  def derivative(value):return float(np.sum(nn*expit(value+b))-kk)
  target=left if derivative(left)>=0 else right if derivative(right)<=0 else brentq(derivative,left,right)
  proposed[j]=(target+e.L)/(2*e.L)
 profile=objective(proposed,'conditional_founder_profile_full_recheck')
 if profile.get('valid') and profile['loss']<best['loss']-1e-9:best=profile;bestz=proposed;accept+=1

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
    if value.get('valid') and value['loss']<best['loss']-1e-9:
     best=value;bestz=zz;accept+=1;a.write(folder/'checkpoint.json',a.clean(best))
   if accept==before:step*=.5
 except Budget:pass
 # Retain source when every local proposal fails.
 best.update(candidate=dict(c,id='refined_'+cid,parent_candidate_id=cid,origin='Native-corrected bounded local refinement'),source_candidate_id=cid,status='native_corrected_approximation',correction_path=str(cp.relative_to(r)),source_x=source_x.tolist(),evaluations=calls,accepted_moves=accept,elapsed_seconds=time.monotonic()-started,trust_region=dict(max_log_biology_change=.08,max_founder_logodds_change=3.,max_absolute_founder_fraction_change=.05,max_dmax_change=.04,max_q_change=.06),source_corrected_loss=initial['loss'],fixed_native_microscopy_bias=fixed_native_bias,native_corrected_comparison_loss=best['data_loss']+fixed_native_bias+best['assay_deviance']+best['ridge_penalty'],native_corrected_microscopy_estimate=best['data_loss']+fixed_native_bias)
 a.write(folder/'final.json',a.clean(best));a.write(folder/'trials.json',a.clean(records))
 # Native agent consumes refined_<source> as a distinct candidate.
 out=r/'candidates'/('refined_'+cid);out.mkdir(parents=True,exist_ok=True)
 a.write(out/'final.json',a.clean(best))
 print(cid,'refinement',calls,accept,best['loss'],flush=True)
