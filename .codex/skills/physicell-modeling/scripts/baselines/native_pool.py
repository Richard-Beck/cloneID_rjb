"""Finite best-plus-diverse native allocation from fresh current-run saved fits."""
from pathlib import Path
import hashlib
import json
import math


def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def select(run,config,stage):
    import workflow as w
    run=Path(run);root=run/'lineage';destination=root/(stage+'_native_candidates.json')
    if destination.exists():raise ValueError('Native pool already frozen')
    identity=read(run/'run_identity.json');input_hash=sha(run/'input_manifest.json')
    candidates=read(root/(stage+'_candidates.json'));pool=config['lineage']['native_pool'];bounds=config['lineage']['natural_bounds'];width=[math.log(b/a) for a,b in bounds]
    if stage=='ridge':width*=2
    records=[];unavailable=[]
    for index,c in enumerate(candidates):
        path=root/'candidates'/c['id']/'final.json'
        if not path.exists():unavailable.append({'candidate_id':c['id'],'reason':'missing_final'});continue
        final=read(path);proof_path=path.with_name('final_provenance.json')
        if not proof_path.exists():unavailable.append({'candidate_id':c['id'],'reason':'incomplete_finalization_provenance'});continue
        proof=read(proof_path)
        if proof.get('run_id')!=identity['run_id'] or proof.get('candidate_id')!=c['id'] or proof.get('input_manifest_sha256')!=input_hash or proof.get('final_sha256')!=sha(path):raise ValueError('Native allocation final provenance mismatch: '+c['id'])
        x=final.get('x',[]);loss=final.get('loss')
        if final.get('invalid') or final.get('valid') is False or not isinstance(loss,(int,float)) or not math.isfinite(loss) or len(x)!=len(width) or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in x):unavailable.append({'candidate_id':c['id'],'reason':'invalid_saved_final'});continue
        records.append({'candidate_index':index,'candidate_id':c['id'],'alpha':c['alpha'],'objective':loss,'x':x,'final_sha256':sha(path)})
    selected=[];audits=[]
    for alpha in ([0.] if stage=='shared' else config['lineage']['alphas']):
        group=sorted((q for q in records if q['alpha']==alpha),key=lambda q:(q['objective'],q['candidate_id']));target=pool['shared'] if stage=='shared' else pool['ridge_per_alpha'];n=min(target,len(group));best=min(n,max(1,math.ceil(n*pool['best_fraction']))) if n else 0
        chosen=[dict(q,selection_basis='best_saved_approximation_objective') for q in group[:best]];left=group[best:]
        while len(chosen)<n:
            def distance(q):return min(sum(((a-b)/d)**2 for a,b,d in zip(q['x'],p['x'],width)) for p in chosen)
            q=min(left,key=lambda q:(-distance(q),q['objective'],q['candidate_id']));chosen.append(dict(q,selection_basis='maximin_saved_parameter_diversity'));left.remove(q)
        selected.extend(chosen);audits.append({'alpha':alpha,'requested_native_sources':target,'available_valid_fits':len(group),'selected':len(chosen)})
    for i,q in enumerate(selected):q['pool_index']=i
    selected_ids={q['candidate_id'] for q in selected}
    for c in candidates:
        if c['id'] in selected_ids:continue
        folder=root/'candidates'/c['id'];files={}
        for name in ['final.json','slots.json','final_provenance.json','attempt_identity.json']:files[name]=sha(folder/name) if (folder/name).exists() else None
        if (folder/'slots.json').exists():
            for i,_ in enumerate(read(folder/'slots.json')):
                for name in ['outcome.json','observables.npz']:files[f'simulations/{i:03}/{name}']=None
        final=read(folder/'final.json') if (folder/'final.json').exists() else {}
        w.write(folder/'score.json',{'candidate':c,'status':'not_native_selected','ranking_score':None,'ranking_basis':'unvalidated_approximation','reason':'Bounded best-plus-diverse native allocation; not a failed scientific simulation','approximation_data_loss':final.get('data_loss'),'assumption_penalty':final.get('assumption_penalty'),'search_objective':final.get('loss'),'x':final.get('x'),'score_evidence':{'candidate':c,'files':files}})
    w.write(destination,selected);w.write(root/(stage+'_native_selection.json'),{'stage':stage,'run_id':identity['run_id'],'input_manifest_sha256':input_hash,'pool_manifest_sha256':sha(destination),'policy':pool,'selected':selected,'groups':audits,'unavailable_fits':unavailable,'candidate_manifest_sha256':sha(root/(stage+'_candidates.json')),'native_evaluations_not_run_for_unselected':True,'historical_parameter_reuse':False})
    return selected
