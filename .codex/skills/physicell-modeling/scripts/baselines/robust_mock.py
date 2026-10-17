"""Degraded-run orchestration checks using invented saved artifacts only."""
import copy
import hashlib
import json
import os

import workflow as w
import scheduler as s


def run(out, stamp, config, check, expect_failure):
    config=copy.deepcopy(config);config['execution']['authorized']=True
    config_path=out/'robust_config.json';w.write(config_path,config)
    run=w.prepare(config,config_path,'robust_synthetic_'+stamp)
    starts=w.read(run/'lineage/shared_candidates.json')
    def scores(values):
        w.write(run/'lineage/shared_scores.json',values)
        w.write(run/'lineage/shared_score_provenance.json',{'run_id':run.name,'scores_sha256':w.sha(run/'lineage/shared_scores.json'),'input_manifest_sha256':w.sha(run/'input_manifest.json')})
    values=[{'status':'complete','candidate':c,'x':c['initial'],'simulator_data_loss':loss,'approximation_data_loss':loss,'assumption_penalty':0.} for c,loss in zip(starts,[10.,50.])]
    scores(values[:1]);candidates=w.prepare_perspective(run)
    check('single_parent_generates_all_configured_starts',len(candidates)==len(config['perspective']['alphas'])*config['perspective']['starts_per_alpha'] and {c['parent'] for c in candidates}=={starts[0]['id']})
    check('single_parent_retains_one_anchor_without_duplication',len(w.read(run/'perspective/anchors.json'))==1)
    # All proposed model embeddings may genuinely fail. A separately evaluated
    # current-run fresh design may still supply useful initialization.
    parents=w.embedding_parents(run)
    for i,parent in enumerate(parents):
        fresh=parent['ranking_basis']=='fresh_unfitted_initial'
        evaluation={'valid':fresh,'loss':1e26,'data_loss':1e26,'assay_deviance':0.,'assumption_penalty':0.,'ridge_penalty':0.,'x':parent['x']}
        w.write(run/'perspective/embedding_checks'/f'{i}.json',{'parent':parent['id'],'parent_sha256':hashlib.sha256(json.dumps(parent,sort_keys=True,allow_nan=False).encode()).hexdigest(),'valid':fresh,'evaluation':evaluation})
    eligible=w.finalize_embeddings(run)
    check('invalid_fitted_parents_can_use_actually_evaluated_fresh_design',len(eligible)==1 and eligible[0].startswith('fresh_initial_') and w.read(run/'perspective/embedding_check.json')['fresh_initialization_fallback'])
    selected=w.read(run/'perspective/candidates.json')[0];folder=run/'perspective/candidates'/selected['id']
    w.write(folder/'attempt_identity.json',{'run_id':run.name,'candidate':selected,'input_manifest_sha256':w.sha(run/'input_manifest.json')})
    w.write(folder/'checkpoint.json',{'valid':True,'loss':1e26,'data_loss':1e26,'assay_deviance':0.,'ridge_penalty':0.,'assumption_penalty':0.,'x':selected['initial']})
    recovered=w.salvage_perspective_checkpoints(run)
    check('valid_high_loss_interrupted_checkpoint_is_recovered_without_model_call',len(recovered)==1 and w.read(folder/'final.json')['recovery_evaluated_model'] is False)
    w.report_run(run)
    report=w.read(run/'report/results.json')
    check('absent_validation_is_never_full_scientific_completion',not report['complete_scientific_baseline'] and report['degraded_evidence'] and report['perspective']['acceptance']['validation_status']=='unavailable')
    # Missing score output can fall back to a valid final, but modified final
    # provenance remains a hard integrity error.
    fallback=w.prepare(config,config_path,'approximation_fallback_'+stamp);candidate=w.read(fallback/'lineage/shared_candidates.json')[0];directory=fallback/'lineage/candidates'/candidate['id']
    w.write(directory/'final.json',{'x':candidate['initial'],'data_loss':1e26,'loss':1e26,'invalid':False})
    w.write(directory/'final_provenance.json',{'run_id':fallback.name,'candidate_id':candidate['id'],'final_sha256':w.sha(directory/'final.json'),'input_manifest_sha256':w.sha(fallback/'input_manifest.json')})
    check('no_native_scores_can_use_valid_same_run_approximation',w.current_shared_parents(fallback,config)[0]['ranking_basis']=='approximation_fallback')
    proof=w.read(directory/'final_provenance.json');proof['run_id']='foreign';w.write(directory/'final_provenance.json',proof)
    expect_failure('approximation_fallback_rejects_foreign_final',lambda:w.current_shared_parents(fallback,config),'foreign/modified')
    # Administrative trimming has its own saved reason and cannot invent work.
    counts={'oxygen_values':[20.5],'episodes':4};spec=s.campaign_spec(config,config_path,run,counts);plan=s.plan(spec,out/'trim_plan',materialize=True)
    jobs={node['name']:str(80000+i) for i,node in enumerate(plan['nodes'])}
    w.write(run/'scheduler_submission.json',{'jobs':jobs,'plan_path':str(out/'trim_plan/plan.json')})
    calls=[];previous=os.environ.get('SLURM_JOB_ID');os.environ['SLURM_JOB_ID']='synthetic_only'
    try:
        trimmed=s.trim_unused(run,{'perspective_search':0},executor=lambda argv:calls.append(argv))
        check('empty_dynamic_branch_cancels_only_own_reserved_job',calls==[['scancel',jobs['perspective_search']]] and trimmed['perspective_search']['scientific_failure'] is False)
        expect_failure('dynamic_manifest_cannot_exceed_frozen_quota',lambda:s.trim_unused(run,{'perspective_search':10**9},executor=lambda argv:calls.append(argv)),'exceeds frozen quota')
    finally:
        if previous is None:os.environ.pop('SLURM_JOB_ID',None)
        else:os.environ['SLURM_JOB_ID']=previous
    w.write(out/'robust_results.json',{'synthetic':True,'scientific_model_calls':0,'scheduler_calls':0,'actual_scheduler_executor_used':False,'source_run':str(run)})
