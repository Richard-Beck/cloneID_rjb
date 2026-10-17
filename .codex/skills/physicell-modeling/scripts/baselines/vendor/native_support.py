"""Explicit finite native support; full-support objective calls are unchanged.

Partial scores are diagnostics: each component's observed finite weight is scaled
back to its requested mass, independently per replicate. A missing component has
no score. Such diagnostics are never exposed as full native losses.
"""
from pathlib import Path
import hashlib
import json
import math
import xml.etree.ElementTree as ET
import numpy as np

COMPONENT_COLUMNS=((0,),(1,),(2,),tuple(range(5,30)),(3,),(4,))


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite_support(predicted,observed,scales,weights,coefficients,seen=None):
    p=np.asarray(predicted,float);o=np.asarray(observed,float);s=np.asarray(scales,float)
    w=np.asarray(weights,float);coef=np.asarray(coefficients,float)
    if p.shape!=o.shape or p.shape!=s.shape or p.ndim!=2 or p.shape[1]!=30 or w.shape!=(len(p),6):
        raise ValueError('Incorrect native support array shapes')
    if np.any(w<0) or not np.isfinite(w).all() or coef.shape!=(6,) or np.any(coef<0) or not np.isfinite(coef).all():
        raise ValueError('Invalid native support weights')
    seen=np.ones(len(p),int) if seen is None else np.asarray(seen)
    if seen.shape!=(len(p),):raise ValueError('Incorrect native support seen shape')
    valid=np.column_stack([np.isfinite(p[:,cols]).all(axis=1)&np.isfinite(o[:,cols]).all(axis=1)&np.isfinite(s[:,cols]).all(axis=1)&(s[:,cols]>0).all(axis=1) for cols in COMPONENT_COLUMNS])
    # Finite inputs can still overflow the squared residual; preserve true invalidity.
    q=p.copy();r=o.copy();q[:,3]=np.maximum(q[:,3],0);r[:,3]=np.maximum(r[:,3],0)
    with np.errstate(over='ignore',invalid='ignore',divide='ignore'):
        residual=((q-r)/s)**2
        residual=np.column_stack([residual[:,0],residual[:,1],residual[:,2],np.mean(residual[:,5:],axis=1),residual[:,3],residual[:,4]])
    valid &= np.isfinite(residual)&(seen[:,None]==1)
    active=(w>0)&(coef[None,:]>0);mask=valid&active
    requested=w.sum(axis=0);available=np.where(mask,w,0).sum(axis=0)
    fractions=np.divide(available,requested,out=np.ones(6),where=requested>0)
    complete=bool(np.all(~active|valid)) and bool(np.any(active))
    present=(requested>0)&(coef>0);scorable=bool(np.any(mask))
    normalized=np.where(mask,w,0)*np.divide(requested,available,out=np.zeros(6),where=available>0)[None,:]
    component_complete=bool(np.all(~present|(available>0)))
    return dict(mask=mask,weights=normalized,complete=complete,scorable=scorable,all_components_available=component_complete,
                component_weight_fraction=fractions,requested_component_weight=requested,supported_component_weight=available,
                weight_fraction=float(np.sum(available*coef)/np.sum(requested*coef)) if np.sum(requested*coef)>0 else 0.,
                supported_rows=np.flatnonzero(np.any(mask,axis=1)),missing_components=np.flatnonzero(present&(available==0)))


def score_support(predicted,observed,scales,weights,coefficients,offset,score_function,seen=None,mask_override=None):
    """Return full loss only with complete support, plus a labelled partial diagnostic.

    A component with zero native support is unavailable; it is omitted from the
    diagnostic sum and listed explicitly. Ranking requires at least one component.
    mask_override permits exact matched-support approximation comparisons.
    """
    info=finite_support(predicted,observed,scales,weights,coefficients,seen)
    if mask_override is not None:
        mask=np.asarray(mask_override,bool)
        if mask.shape!=info['mask'].shape or np.any(mask&~info['mask']):
            raise ValueError('Matched support is not finite in comparison predictions')
        requested=np.asarray(weights,float).sum(axis=0);available=np.where(mask,weights,0).sum(axis=0)
        info.update(mask=mask,weights=np.where(mask,weights,0)*np.divide(requested,available,out=np.zeros(6),where=available>0)[None,:],complete=False,scorable=bool(mask.any()),component_weight_fraction=np.divide(available,requested,out=np.ones(6),where=requested>0),supported_component_weight=available,weight_fraction=float(np.sum(available*np.asarray(coefficients))/np.sum(requested*np.asarray(coefficients))) if np.sum(requested*np.asarray(coefficients))>0 else 0.,supported_rows=np.flatnonzero(np.any(mask,axis=1)),missing_components=np.flatnonzero((requested>0)&(available==0)))
    record={k:v.tolist() if isinstance(v,np.ndarray) else v for k,v in info.items() if k!='weights'}
    record.update(normalization='Each retained component is rescaled to its original requested weight mass; missing components are omitted and explicitly unavailable.',full_loss=None,partial_loss=None,ranking_loss=None,weighted_components=None)
    if not info['scorable']:
        record['ranking_basis']='unavailable';return record
    loss,_,parts=score_function(predicted,observed,scales,weights if info['complete'] and mask_override is None else info['weights'],coefficients,offset=offset)
    if not np.isfinite(loss) or not np.isfinite(parts).all():
        record.update(ranking_basis='unavailable',score_error='Nonfinite weighted native objective');return record
    record['weighted_components']=parts.tolist();record['ranking_loss']=float(loss)
    if info['complete'] and mask_override is None:
        record.update(full_loss=float(loss),ranking_basis='native_full')
    else:
        record.update(partial_loss=float(loss),ranking_basis='native_partial_normalized')
    return record


def timed_snapshots(directory):
    result=[];errors=[]
    for path in sorted(Path(directory).glob('output*.xml')):
        try:
            root=ET.parse(path).getroot();value=float(root.find('.//current_time').text)
            if not np.isfinite(value):raise ValueError('Nonfinite snapshot time')
            result.append((value,path))
        except (ET.ParseError,ValueError,AttributeError,OSError) as error:
            errors.append(dict(path=str(path),error=repr(error)))
    return result,errors


def measure_requested(directory,times,measure):
    """Measure only saved snapshots matching exact requested times within 0.5 min."""
    times=np.asarray(times,float);outputs,errors=timed_snapshots(directory)
    values=np.full((len(times),30),np.nan);records=[];available=np.zeros(len(times),bool)
    for i,t in enumerate(times):
        row=dict(requested_minutes=float(t),status='missing')
        if outputs:
            actual,path=min(outputs,key=lambda pair:(abs(pair[0]-t),str(pair[1])))
            row['nearest_minutes']=actual
            if abs(actual-t)<=.500001:
                try:
                    value,metadata=measure(path);value=np.asarray(value,float)
                    if value.shape!=(30,):raise ValueError('Expected 30 native observables')
                    values[i]=value;available[i]=True
                    row.update(status='measured',actual_minutes=actual,path=str(path),metadata=metadata,finite_components=int(np.isfinite(value).sum()))
                except Exception as error:row.update(status='measurement_failed',error=repr(error))
        records.append(row)
    return values,available,records,errors


def ranking_evidence(value):
    """Support-first native ordering metadata; no model or objective call.

    Numeric partial losses are compared only after component availability,
    requested weight coverage, and the exact support-pattern group agree.
    """
    basis=value.get('ranking_basis','native_full' if value.get('status')=='complete' else 'unavailable')
    loss=value.get('ranking_score',value.get('ranking_total',value.get('simulator_data_loss')))
    finite=isinstance(loss,(int,float)) and math.isfinite(loss)
    tier=0 if finite and basis=='native_full' else 1 if finite and basis=='native_partial_normalized' else 2
    native=value.get('native_support',{})
    records=native if isinstance(native,list) else native.get('replicates',[]) if isinstance(native,dict) else []
    components=[];coverage=[];patterns=[]
    for record in records:
        requested=record.get('requested_component_weight',[]);available=record.get('supported_component_weight',[])
        active=[i for i,w in enumerate(requested) if w>0]
        components.append(sum(i<len(available) and available[i]>0 for i in active)/len(active) if active else 0.)
        fraction=record.get('weight_fraction',0.)
        coverage.append(float(fraction) if isinstance(fraction,(int,float)) and math.isfinite(fraction) else 0.)
        patterns.append(record.get('mask',[]))
    component_fraction=sum(components)/len(components) if components else 1. if tier==0 else 0.
    weight_fraction=sum(coverage)/len(coverage) if coverage else 1. if tier==0 else float(native.get('weight_fraction',0.)) if isinstance(native,dict) else 0.
    pattern='full' if tier==0 else hashlib.sha256(json.dumps(patterns,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return dict(tier=tier,component_fraction=component_fraction,weight_fraction=weight_fraction,pattern_sha256=pattern,
                ordering='full native, then partial component availability, requested weight coverage, exact support-pattern group, numeric loss, candidate ID')


def ranking_key(value,loss=None):
    evidence=ranking_evidence(value)
    if loss is None:loss=value.get('ranking_score',value.get('ranking_total',value.get('simulator_data_loss')))
    numeric=float(loss) if isinstance(loss,(int,float)) and math.isfinite(loss) else math.inf
    candidate=value.get('candidate',{}).get('id',value.get('candidate_id',value.get('id','')))
    return (evidence['tier'],-evidence['component_fraction'],-evidence['weight_fraction'],evidence['pattern_sha256'],numeric,candidate)
