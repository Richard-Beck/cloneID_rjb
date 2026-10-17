"""Budget, storage and selected-native DAG tests; no models or processes."""
from pathlib import Path
import copy
import json
import os
import shutil

import workflow as w
import scheduler
import storage_budget as st
import campaign_budget as cb
import native_pool


def run(out,stamp,config,check,expect_failure):
    cfg=copy.deepcopy(config);plan=st.storage_plan(cfg)
    check('storage_decimal_durable_and_all_volume_peak_bounds',plan['valid'] and plan['durable_ceiling_bytes']<=50_000_000_000 and plan['peak_reserved_bytes']<=100_000_000_000)
    changed=copy.deepcopy(cfg);changed['storage']['case_reservation_bytes']=100_000_000
    check('storage_rejects_overcommitted_parallel_cases',not st.storage_plan(changed)['valid'])
    changed=copy.deepcopy(cfg);changed['perspective']['conditional']['finalists']=1000
    check('storage_recomputes_configured_case_durable_bound',not st.storage_plan(changed)['valid'])
    changed=copy.deepcopy(cfg);changed['storage']['jit_disk_cache']=True
    check('unbounded_persistent_jit_cache_not_admitted',not st.storage_plan(changed)['valid'])
    root=out/'footprint';root.mkdir();(root/'a').write_bytes(b'input');os.link(root/'a',root/'hardlink');shutil.copy2(root/'a',root/'copy');(root/'link').symlink_to(root/'a')
    inv=st.inventory([root]);check('inventory_counts_copies_and_deduplicates_hardlinks',inv['files']==2 and inv['symlinks']==1 and inv['bytes']>=10)
    dangling=root/'container_pandoc';dangling_target=out/'absent_container_software/pandoc';dangling.symlink_to(dangling_target)
    inv=st.inventory([root]);entry=inv['dangling_symlinks'][0]
    check('dangling_container_symlink_counts_inode_but_no_missing_target_bytes',inv['files']==2 and inv['symlinks']==2 and inv['bytes']>=dangling.lstat().st_blocks*512 and entry=={'path':str(dangling),'target':str(dangling_target),'target_bytes':0})
    sparse=root/'sparse'
    with sparse.open('wb') as handle:handle.seek(8*1024*1024-1);handle.write(b'x')
    inv=st.inventory([root])
    allocated=sum(p.lstat().st_blocks*512 for p in [root,root/'a',root/'copy',root/'link',dangling,sparse])
    check('sparse_extents_are_not_charged_as_allocated_disk',inv['bytes']==inv['allocated_bytes']==allocated and inv['accounting_basis']=='allocated_blocks')
    check('logical_payload_is_reported_separately',inv['logical_file_bytes']==8*1024*1024+10)
    invfile=out/'inventory.json';w.write(invfile,inv)
    loaded=st.frozen_inventory(invfile,w.sha(invfile),[root],[],clock=lambda:inv['inventory_unix']+1)
    check('inventory_snapshot_is_hash_bound_fresh_and_same_ownership',loaded['verified'] and loaded['snapshot_age_seconds']==1)
    wrong=copy.deepcopy(inv);wrong['bytes']+=1;w.write(invfile,wrong)
    try:st.frozen_inventory(invfile,w.sha(invfile),[root],[],clock=lambda:inv['inventory_unix']+1)
    except ValueError:check('mixed_logical_and_physical_snapshot_is_rejected',True)
    else:raise AssertionError('Inconsistent allocation basis accepted')
    w.write(invfile,inv)
    try:st.frozen_inventory(invfile,w.sha(invfile),[root],[],clock=lambda:inv['inventory_unix']+601)
    except ValueError:check('stale_inventory_cannot_authorize_launch',True)
    else:raise AssertionError('Stale inventory accepted')
    outside=out/'external_created';outside.write_bytes(b'external');(root/'hidden').symlink_to(outside)
    try:st.inventory([root])
    except ValueError as error:check('inventory_refuses_hidden_external_storage','Uninventoried external' in str(error))
    else:raise AssertionError('External copy was hidden')
    (root/'hidden').unlink()
    test=out/'reserved_cases';test.mkdir();local=copy.deepcopy(cfg);local['storage']['native_case_slots']=1
    st.initialize(test,local,{'bytes':0,'verified':True});case=test/'transient/one'
    try:
        with st.reserve_case(test,local,'one',case):
            case.mkdir();(case/'payload').write_bytes(b'transient')
            try:
                with st.reserve_case(test,local,'two',test/'transient/two'):raise AssertionError('Second reservation admitted')
            except ValueError as error:check('reservation_precedes_native_export_and_limits_concurrency','exhausted' in str(error))
            raise RuntimeError('synthetic interrupted worker')
    except RuntimeError:pass
    check('worker_failure_deletes_raw_but_preserves_compact_overlap_reservation',not case.exists() and w.read(test/'storage/state.json')['native_active']['one']['compact_finalization_unverified'])
    reserve,commit,release=st.asset_callbacks(test,local);asset=test/'field_frame_0.bin';asset.write_bytes(b'precise');token=reserve(7,asset,{'synthetic':True});commit(token,{'sha256':w.sha(asset)});release(token)
    check('field_asset_lease_tracks_exact_bytes',not st.ledger_snapshot(test)['field_assets'])
    orphan=test/'field_frame_0001.bin';orphan.write_bytes(b'owned');token=reserve(5,orphan,{'synthetic':True})
    unrelated=test/'unrelated.bin';unrelated.write_bytes(b'keep')
    st.cleanup_unretained_assets(test,[])
    check('janitor_closes_unmanifested_owned_field_without_touching_unrelated_files',not orphan.exists() and unrelated.exists() and not st.ledger_snapshot(test)['field_assets'])
    closed=test/'transient/closed_check'
    with st.reserve_case(test,{**local,'storage':{**local['storage'],'native_case_slots':2}},'closed_check',closed) as lease:lease['completion_verified']=False
    check('normally_caught_wrapper_failure_retains_unclosed_compact_lease',w.read(test/'storage/state.json')['native_active']['closed_check']['compact_finalization_unverified'])
    cb.initialize(test,local,clock=lambda:100.)
    check('one_execution_clock_has_science_and_report_reserves',cb.remaining(test,clock=lambda:200.)==3200. and cb.remaining(test,False,clock=lambda:200.)==3500.)
    check('late_task_allowance_is_clipped',cb.clip_seconds(test,300,clock=lambda:3390.)==10.)
    check('expired_science_is_not_admitted',not cb.admitted(test,clock=lambda:3401.))
    # Janitor must preserve raw bytes and leases until the scheduler is quiescent.
    w.write(test/'scheduler_submission.json',{'jobs':{'science':'100','budget_controller':'101','budget_janitor':'102'}});case.mkdir();(case/'payload').write_bytes(b'keep')
    try:cb.janitor(test,local,executor=lambda argv:'100|COMPLETING\n')
    except ValueError:check('janitor_will_not_delete_owned_live_outputs',(case/'payload').exists())
    else:raise AssertionError('Janitor deleted an active case')
    # Test pure deterministic selected-pool allocation with source proofs.
    native=out/'pool_case';(native/'lineage').mkdir(parents=True);w.write(native/'run_identity.json',{'run_id':'pool_case'});w.write(native/'input_manifest.json',{'synthetic':True});candidates=[]
    width=len(cfg['lineage']['natural_bounds'])
    for i,loss in enumerate([4.,1.,2.,3.]):
        c={'id':'shared_'+str(i),'stage':'shared','alpha':0.,'run_id':'pool_case','initial':[float(i)]*width};candidates.append(c);d=native/'lineage/candidates'/c['id'];w.write(d/'final.json',{'x':[float(i)]*width,'loss':loss,'data_loss':loss,'assumption_penalty':0.});w.write(d/'slots.json',[])
        w.write(d/'final_provenance.json',{'run_id':'pool_case','candidate_id':c['id'],'input_manifest_sha256':w.sha(native/'input_manifest.json'),'final_sha256':w.sha(d/'final.json')})
    w.write(native/'lineage/shared_candidates.json',candidates);local_pool=copy.deepcopy(cfg);local_pool['lineage']['native_pool'].update(shared=2,best_fraction=.5)
    chosen=native_pool.select(native,local_pool,'shared')
    check('native_pool_best_plus_diverse_maps_original_indices',[q['candidate_index'] for q in chosen]==[1,3] and [q['pool_index'] for q in chosen]==[0,1])
    check('unselected_fits_are_unvalidated_not_failed_simulations',w.read(native/'lineage/candidates/shared_0/score.json')['status']=='not_native_selected')
    proof=w.read(native/'lineage/shared_native_selection.json');check('native_pool_freezes_candidate_and_final_hashes',proof['pool_manifest_sha256']==w.sha(native/'lineage/shared_native_candidates.json') and all(q['final_sha256']==w.sha(native/'lineage/candidates'/q['candidate_id']/'final.json') for q in chosen))
    # Scheduler plans contain no process calls and cap the controller plus workers.
    counts={'oxygen_values':[0.,.1,.2,.3,.5,1.,2.,20.5],'episodes':118};source=copy.deepcopy(w.load_config(w.DEFAULT_CONFIG));source['paths']['scratch_root']=str(out);source['paths']['output_root']=str(out/'runs');path=out/'storage_plan_config.json';w.write(path,source);source=w.load_config(path)
    spec=scheduler.campaign_spec(source,path,out/'PLANNED_ONLY',counts);schedule=scheduler.plan(spec,out/'storage_scheduler',materialize=True);nodes={n['name']:n for n in schedule['nodes']}
    check('new_campaign_has_no_scientific_postvalidation_nodes',spec['post_validation_adaptive_nodes']==[] and schedule['no_scheduler_calls'])
    check('selected_native_default_counts_are10496_plus4488',nodes['lineage_shared_native']['tasks']==4096+256 and nodes['lineage_ridge_native']['tasks']==6400+200 and nodes['perspective_screen_native']['tasks']==2688 and nodes['perspective_final_native']['tasks']==1800)
    check('controller_reserved_inside_global_cpu_cap',spec['max_cpus']==1000 and spec['worker_cpu_cap']==999 and any('--array=0-2687%999'==v for v in nodes['perspective_screen_native']['submit_command']))
    check('perspective_fits_have_one_wave',nodes['perspective_search']['tasks']==996 and not any('%' in v for v in nodes['perspective_search']['submit_command'] if v.startswith('--array')))
    check('janitor_depends_on_every_prior_job',set(nodes['budget_janitor']['depends_on_all'])==set(nodes)-{'budget_janitor'})
    for stage,total in [('shared',4096),('ridge',6400)]:
        manifest=nodes['lineage_'+stage+'_native']['manifest_value'];seen=set();parents={};scores=[]
        for group in manifest['task_groups']:
            if group['phase']=='simulate':
                check('native_membership_disjoint_'+stage+'_'+str(group['candidate']),not seen.intersection(group['indices']));seen.update(group['indices']);parents[group['candidate']]=group['indices']
            else:scores.append(group)
        check('native_mapping_and_all_parent_barrier_'+stage,len(seen)==total and all(g['parents']==parents[g['candidate']] for g in scores) and manifest['candidate_index_space']=='native_pool' and manifest['parent_finalizer_offset']==(512 if stage=='shared' else 500))
    import sys
    sys.path.insert(0,str(w.PACKAGE/'vendor'))
    from bounded_trace import Trace
    trace=Trace(out/'bounded_trace.jsonl',10);trace.write('12345\n');trace.write('67890\n');trace.close();summary=w.read(out/'bounded_trace.jsonl.summary.json')
    check('fit_trace_limits_storage_without_hiding_omission',summary['records_seen']==2 and summary['records_retained']==1 and summary['records_omitted']==1 and (out/'bounded_trace.jsonl').stat().st_size<=10)
    w.write(out/'storage_aware_checks.json',{'passed':True,'no_scientific_calls':True,'no_scheduler_calls':True,'default_storage_plan':st.storage_plan(source),'default_scheduler_tasks':schedule['total_array_tasks']})
