"""Authorized optimization-only campaign; original no-WGD objective unchanged."""
from pathlib import Path
import argparse, hashlib, importlib.util, json, os, signal, sys, time, traceback
import numpy as np
from scipy.special import expit, logit
from scipy.stats import qmc
import perspective_model as a

ROOT = Path(__file__).resolve().parents[1]
ROOT = None  # Set to the new run by the guarded worker.
SECONDS = 300.
SEED = 202610161906
ACTIVE = np.array([j for j in range(33) if j != 2])
EPS = 1e-12
L = float(logit(1-EPS))
WIDTH = np.diff(a.BOUNDS, axis=1).ravel()

def write(path, value):
    a.write(path, a.clean(value))

def encode(x):
    z = (np.asarray(x)-a.BOUNDS[:,0])/WIDTH
    z[:2] = (logit(np.clip(x[:2],EPS,1-EPS))+L)/(2*L)
    return np.clip(z[ACTIVE], 0., 1.)

def decode(z):
    full = np.zeros(33)
    full[ACTIVE] = z
    x = a.BOUNDS[:,0]+WIDTH*full
    x[:2] = expit(2*L*full[:2]-L)
    x[2] = np.log(1e-12)
    return np.clip(x, a.BOUNDS[:,0], a.BOUNDS[:,1])

def founder_draw(rng):
    u = rng.random()
    low = 10**rng.uniform(-9,np.log10(.5)) if u < .6 else rng.uniform(.01,.99) if u < .85 else 1-10**rng.uniform(-8,-.31)
    high = 1-10**rng.uniform(-9,np.log10(.5)) if rng.random()<.75 else rng.uniform(.01,.99)
    return [low,high]



def fit(index):
    c=a.read(ROOT/'candidates.json')[index]
    folder=ROOT/'candidates'/c['id'];folder.mkdir(parents=True,exist_ok=True)
    if (folder/'checkpoint.json').exists():raise RuntimeError('Existing checkpoint: never overwrite or restart a completed attempt')
    data=a.Data();rng=np.random.default_rng(c['seed'])
    # Warm Numba dispatch/cache outside the requested optimizer allowance.
    warm_started=time.monotonic()
    warm=a.evaluate(data,np.asarray(c['fallback_initial']),c['alpha'],'no_wgd')
    write(folder/'warmup.json',dict(warm,x=c['fallback_initial'],candidate=c,evaluation_basis='actual_warmup_evaluation'))
    # A failed warmup point is not a reason to discard other valid starts.
    warm_seconds=time.monotonic()-warm_started
    started=time.monotonic();deadline=started+SECONDS;calls=0;accepted=0;tested=set();sweep=0
    from bounded_trace import Trace
    traces=Trace(folder/'trials.jsonl',524288)
    moves=Trace(folder/'accepted_moves.jsonl',131072)
    cache={};best=None
    class BudgetReached(Exception):pass
    def stop_signal(signum,frame):raise BudgetReached()
    signal.signal(signal.SIGTERM,stop_signal)
    def trial(x,label):
        nonlocal calls
        if time.monotonic()>=deadline:raise BudgetReached()
        x=np.asarray(x);key=x.astype('<f8').tobytes()
        if key in cache:return cache[key]
        value=a.evaluate(data,x,c['alpha'],'no_wgd');calls+=1
        value=dict(value,x=x.tolist(),evaluations=calls,elapsed_seconds=time.monotonic()-started)
        record=dict(evaluation=calls,label=label,x=x.tolist(),loss=value['loss'],data_loss=value.get('data_loss'),assay_deviance=value.get('assay_deviance'),ridge_penalty=value.get('ridge_penalty'),assumption_penalty=value.get('assumption_penalty'),valid=bool(value.get('valid')),elapsed_seconds=value['elapsed_seconds'])
        traces.write(json.dumps(a.clean(record))+'\n');cache[key]=value
        return value
    screening=[];proposal=np.asarray(c['initial']);parent=np.asarray(c['parent_x']);fallback=np.asarray(c['fallback_initial'])
    attempts=[proposal]+[decode(encode(parent)+scale*(encode(proposal)-encode(parent))) for scale in [.5,.2,.05]]+[fallback]
    reason='time_budget'
    try:
        for attempt,x in enumerate(attempts):
            if time.monotonic()-started>45 and attempt<len(attempts)-1:continue
            out=trial(x,dict(phase='initial_screen',attempt=attempt));screening.append(dict(attempt=attempt,valid=bool(out.get('valid')),loss=out['loss']))
            if out.get('valid') and np.isfinite(out['loss']):
                best=out;break
        if best is None:
            write(folder/'outcome.json',dict(status='invalid_initialization',screening=screening));return
        z=encode(np.asarray(best['x']));write(folder/'checkpoint.json',best)
        write(folder/'initialization.json',dict(candidate=c,actual_initial=best['x'],screening=screening,initial_loss=best['loss'],warmup_seconds=warm_seconds))
        # Step sizes are fractions of transformed bounds, not tiny derivative probes.
        step=np.full(32,[.025,.04,.065][index%3]);step[:2]=.8/(2*L)
        step[np.where(ACTIVE==3)[0][0]]=.06;step[np.where(ACTIVE==4)[0][0]]=.12
        for j in [18,31]:
            k=np.where(ACTIVE==j)[0][0]
            tau=np.exp(best['x'][j]);cross_grid=np.log1p(24*max(data.dt.values())/tau)
            step[k]=max(step[k],cross_grid/WIDTH[j])
        coordinate_signs=rng.choice([-1,1],32)
        while time.monotonic()<deadline:
            sweep+=1;before=accepted
            directions=[]
            for k in rng.permutation(32):
                d=np.zeros(32);d[k]=1;directions.append((a.PARAMETERS[ACTIVE[k]],d))
            if sweep>1:
                paired=[]
                for j in rng.permutation(13):
                    lo=np.where(ACTIVE==7+j)[0][0];hi=np.where(ACTIVE==20+j)[0][0]
                    d=np.zeros(32);d[[lo,hi]]=1;paired.append(('mean_'+a.NAMES[j],d))
                    d=d.copy();d[hi]=-1;paired.append(('contrast_'+a.NAMES[j],d))
                # Interleave coordinate and paired moves so neither is starved.
                directions=[v for pair in zip(directions[:26],paired) for v in pair]+directions[26:]
            for label,d in directions:
                nonzero=np.flatnonzero(d)
                sign=int(coordinate_signs[nonzero[0]]*(-1)**(sweep-1)) if len(nonzero)==1 else (1 if rng.random()<.5 else -1)
                zz=np.clip(z+sign*step*d,0.,1.)
                if np.array_equal(z,zz):zz=np.clip(z-sign*step*d,0.,1.);sign=-sign
                if np.array_equal(z,zz):continue
                value=trial(decode(zz),dict(phase='search',sweep=sweep,direction=label,sign=sign))
                tested.update(ACTIVE[np.flatnonzero(zz!=z)].tolist())
                if value.get('valid') and value['loss']<best['loss']-1e-9:
                    accepted+=1;moves.write(json.dumps(a.clean(dict(move=accepted,evaluation=calls,sweep=sweep,direction=label,sign=sign,before_loss=best['loss'],after_loss=value['loss'],before_x=best['x'],after_x=value['x'])))+'\n')
                    z=zz;best=value;write(folder/'checkpoint.json',best)
            if accepted==before:step*=.6
            elif sweep%3==0:step*=.85
    except BudgetReached:reason='time_budget'
    except Exception:
        reason='error';write(folder/'error.json',dict(traceback=traceback.format_exc()))
        raise
    finally:
        if best is None and warm.get('valid') and np.isfinite(warm.get('loss',np.inf)):
            best=dict(warm,x=c['fallback_initial'],evaluations=calls,initialization_basis='saved_valid_warmup_after_interruption')
            write(folder/'checkpoint.json',best)
        traces.close();moves.close()
        status=dict(candidate_id=c['id'],reason=reason,target_seconds=SECONDS,elapsed_seconds=time.monotonic()-started,evaluations=calls,accepted_moves=accepted,sweeps=sweep,active_coordinates=ACTIVE.tolist(),tested_coordinates=sorted(tested),all_active_coordinates_tested=set(ACTIVE.tolist())<=tested,warmup_seconds=warm_seconds,checkpoint_retained=best is not None,job_id=os.environ.get('SLURM_JOB_ID'),array_job_id=os.environ.get('SLURM_ARRAY_JOB_ID'),array_task_id=os.environ.get('SLURM_ARRAY_TASK_ID'),validation_submitted=False)
        write(folder/'checkpoint.json.status.json',status)
        if best is not None:write(folder/'final.json',dict(best,candidate=c,fit_status=status,status='approximation_only'))
        print(c['id'],json.dumps(a.clean(status)),flush=True)
