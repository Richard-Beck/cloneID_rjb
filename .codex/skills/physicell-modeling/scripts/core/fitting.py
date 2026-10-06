"""Dataset-independent rates, exact embeddings, bounded search and score accounting."""
import json, os, time
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n'); tmp.replace(path)


def hill(x, half, exponent):
    x = np.asarray(x, dtype=float)
    if np.any(x < 0) or half <= 0 or exponent <= 0: raise ValueError('Invalid Hill inputs')
    return expit(exponent * (np.log(np.maximum(x, np.finfo(float).tiny)) - np.log(half))) * (x > 0)


def medium_multiplier(x, reference, ratio, half, exponent):
    if ratio <= 0: raise ValueError('Ratio must be positive')
    return (1 + (ratio-1)*hill(x, half, exponent)) / (1 + (ratio-1)*hill(reference, half, exponent))


def sigmoid_rate(s, early, late, midpoint, width):
    """Width is the 10%-90% transition span, in the same units as s."""
    if min(early, late, width) <= 0: raise ValueError('Positive endpoints and width required')
    return early + (late-early)*expit(2*np.log(9)*(np.asarray(s)-midpoint)/width)


def embed_rates(rates, previous, target, branches, midpoint=0., width=1.):
    """Natural-unit G1-rate blocks only; use embed_branch_parameters for other fitted biology."""
    r = np.asarray(rates, dtype=float)
    if previous == 'stationary' and target == 'constant' and r.size == 1:
        return np.repeat(r, branches)
    if previous == 'constant' and target == 'adaptation' and r.size == branches and width > 0:
        return np.column_stack([r, r, np.full(branches, midpoint), np.full(branches, width)])
    raise ValueError('Incompatible nested rate blocks')


def embed_branch_parameters(parameters, previous, target, branches):
    """Embed named non-adapting biological coefficients in natural or search units.

    Stationary scalars become identical branch values. Constant branch values remain
    unchanged in adaptation. Initialization and observation parameters are separate;
    the adapter retains their agreed sharing. Use embed_rates for the G1-rate block.
    """
    if isinstance(branches, bool) or not isinstance(branches, (int, np.integer)) or branches < 1:
        raise ValueError('Positive branch count required')
    if (previous, target) not in (('stationary', 'constant'), ('constant', 'adaptation')):
        raise ValueError('Incompatible biological stages')
    result = {}
    for name, value in parameters.items():
        values = np.asarray(value, dtype=float)
        if not np.isfinite(values).all():
            raise ValueError('Nonfinite biological parameter: ' + name)
        if previous == 'stationary' and target == 'constant' and values.ndim == 0:
            result[name] = np.repeat(values, branches)
        elif previous == 'constant' and target == 'adaptation' and values.shape == (branches,):
            result[name] = values.copy()
        else:
            raise ValueError('Incompatible branch parameter block: ' + name)
    return result


def stratified_starts(bounds, count, seed):
    """Bounds are already in the adapter's declared search coordinates."""
    bounds=np.asarray(bounds, float); rng=np.random.default_rng(seed)
    if count < 1 or np.any(bounds[:,1] <= bounds[:,0]): raise ValueError('Invalid starts/bounds')
    q=np.column_stack([(rng.permutation(count)+rng.random(count))/count for _ in bounds])
    return bounds[:,0] + q*(bounds[:,1]-bounds[:,0])


def diverse_parents(parents, bounds, count, window=.20):
    """Return other competitive parents, farthest first; best handled separately."""
    ranked=sorted(parents, key=lambda c:(c['loss'],c['id']))
    if not ranked: raise ValueError('No scored parents')
    remaining=[p for p in ranked[1:] if p['loss'] <= ranked[0]['loss']*(1+window)]
    span=np.diff(np.asarray(bounds,float),axis=1).ravel(); chosen=[ranked[0]]; result=[]
    while remaining and len(result)<count:
        distances=[min(np.linalg.norm((np.asarray(p['x'])-np.asarray(q['x']))/span) for q in chosen) for p in remaining]
        i=max(range(len(remaining)), key=lambda i:(distances[i],-remaining[i]['loss']))
        p=remaining.pop(i);result.append(p);chosen.append(p)
    return result


def composite_score(predicted, observed, scales, weights, coefficients, offset=None):
    """Matrices contain log density/count, coverage, floored log gap, CE, 25 relative-area quantiles.
    weights: n x 5 episode-balanced weights, ordered count,coverage,area,gap,CE.
    coefficients are explicit; default proposal is [1/3,1/6,1/6,1/6,1/6].
    Returns total, fixed/profiled count offset, weighted components. Reject missing required predictions.
    """
    p=np.asarray(predicted,float).copy(); o=np.asarray(observed,float).copy(); s=np.asarray(scales,float)
    w=np.asarray(weights,float); coef=np.asarray(coefficients,float)
    if p.shape != o.shape or p.shape != s.shape or p.ndim != 2 or p.shape[1] != 29 or w.shape != (len(p),5):
        raise ValueError('Incorrect observation array shapes')
    if coef.shape != (5,) or np.any(coef<0) or np.any(w<0) or not np.isfinite(w).all() or not np.isfinite(coef).all():
        raise ValueError('Invalid weights')
    if offset is None:
        good=w[:,0]>0
        if not good.any(): raise ValueError('Count conversion must be supplied when counts are unsupported')
        cw=w[good,0]/s[good,0]**2
        offset=float(np.sum(cw*(o[good,0]-p[good,0]))/cw.sum())
    p[:,0]+=offset; p[:,2]=np.maximum(p[:,2],0);o[:,2]=np.maximum(o[:,2],0)
    with np.errstate(invalid='ignore',divide='ignore'):
        r=((p-o)/s)**2
        residual=np.column_stack([r[:,0],r[:,1],np.mean(r[:,4:],axis=1),r[:,2],r[:,3]])
    active=(w>0)&(coef[None,:]>0)
    if not np.isfinite(offset) or np.any(active & ~np.isfinite(residual)): raise ValueError('Required residual is not finite')
    parts=np.sum(np.where(active,w*residual,0),axis=0)*coef
    return float(parts.sum()), float(offset), parts


def bounded_search(evaluate, initial, bounds, seconds, checkpoint, ftol=1e-5, xtol=1e-4):
    """evaluate(x) returns a finite JSON record containing loss. Save best atomically before timeout.
    Evaluation time counts toward the budget; an in-progress evaluation can exceed it. SLURM is the hard outer cap.
    """
    bounds=np.asarray(bounds,float);lo=bounds[:,0];span=bounds[:,1]-lo
    if np.any(span<=0) or seconds<=0: raise ValueError('Invalid bounds/budget')
    z=(np.asarray(initial)-lo)/span
    if np.any((z<0)|(z>1)):raise ValueError('Initial point outside bounds')
    start=time.monotonic();best=None;calls=0
    class BudgetReached(Exception): pass
    def objective(z):
        nonlocal best,calls
        if calls and time.monotonic()-start >= seconds: raise BudgetReached()
        x=lo+span*z;record=evaluate(x);calls+=1
        if record is None or not np.isfinite(record['loss']):return 1e30
        if best is None or record['loss']<best['loss']:
            best=dict(record,x=x.tolist(),evaluations=calls,elapsed_seconds=time.monotonic()-start)
            atomic_json(checkpoint,best)
        return float(record['loss'])
    reason='converged'
    try:
        objective(z)
        result=minimize(objective,z,method='Powell',bounds=[(0,1)]*len(z),options=dict(ftol=ftol,xtol=xtol))
        reason='converged' if result.success else str(result.message)
    except BudgetReached:reason='time_budget'
    atomic_json(str(checkpoint)+'.status.json',dict(reason=reason,evaluations=calls,elapsed_seconds=time.monotonic()-start,has_checkpoint=best is not None))
    return best
