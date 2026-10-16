"""Synthetic terminal-protocol and scheduler checks. No models or real scheduler."""
import ast
import copy
import json
import os
import sys
from pathlib import Path

import numpy as np

import workflow as w
import terminal as t
import scheduler as s


def run(out,stamp,check,expect_failure):
    config=copy.deepcopy(w.load_config(w.DEFAULT_CONFIG))
    import synthetic_data
    prepared=synthetic_data.build(out/"invented_pilot_data")
    synthetic_data.configure(config,out,prepared,sys.executable)
    config["lineage"].update(shared_starts=5,ridge_starts_per_alpha=3,alphas=[0.,7.])
    config["perspective"].update(starts_per_alpha=10)
    config_path=out/"terminal_config.json";w.write(config_path,config)
    run=w.prepare(config,config_path,"terminal_synthetic_"+stamp)
    shared=w.read(run/"lineage/shared_candidates.json")
    scores=[{"status":"complete","candidate":c,"x":c["initial"],"simulator_data_loss":10.+i*.1,"approximation_data_loss":10.+i*.2,"assumption_penalty":0.,"synthetic_not_scientific":True} for i,c in enumerate(shared[:2])]
    w.write(run/"lineage/shared_scores.json",scores)
    w.write(run/"lineage/shared_score_provenance.json",{"run_id":run.name,"scores_sha256":w.sha(run/"lineage/shared_scores.json"),"input_manifest_sha256":w.sha(run/"input_manifest.json")})
    candidates=w.prepare_perspective(run);root=run/"perspective";episodes=w.read(run/"inputs/episodes.json")
    for c in candidates:
        index=c["index"];x=c["initial"]
        final={"valid":True,"x":x,"loss":float(index%10+100*(index//10)),"data_loss":float(index%10+1),"assay_deviance":2.,"ridge_penalty":0.,"assumption_penalty":0.,"seed_fractions":{p["episode_id"]:float(x[0 if p["founding_group"]=="2N" else 1]) for p in episodes},"synthetic_not_scientific":True}
        w.write(root/"candidates"/c["id"]/"final.json",final)
    selected=t.select_screen(run)
    check("executed_top5_plus5_screen_count",len(selected)==40)
    anchors=[c for c in selected if c["id"].startswith("anchor_")]
    check("two_anchors_replace_last_diversity_first_two_buckets",len(anchors)==2 and [c["alpha"] for c in anchors]==config["perspective"]["alphas"][:2] and all(selected[i*10+9]["id"].startswith("anchor_") for i in range(2)))
    check("screen_retains_objective_top5_per_alpha",all([c["id"] for c in selected[ai*10:ai*10+5]]==[f"no_wgd_a{ai:02}_{i:04}" for i in range(5)] for ai in range(4)))
    check("screen_sources_are_same_run_and_hashed",all(w.sha(root/c["source"])==c["source_sha256"] for c in selected))
    expect_failure("screen_selection_no_overwrite",lambda:t.select_screen(run),"already frozen")
    pool=[dict(c,final=w.read(root/"candidates"/c["id"]/"final.json")) for c in candidates[:9]]
    expect_failure("missing_finite_screen_support_blocks_selection",lambda:t.quality_diversity(pool,config),"needs 10")
    data=t.Metadata(run,config);passages=t.subset(data,24)
    check("source_subset_is24_unique_passages",len(passages)==24 and len({p["episode_id"] for p in passages})==24)
    check("source_subset_covers_oxygen_and_founders",{(p["oxygen"],p["founding_group"]) for p in passages}=={(o,g) for o in data.dt for g in ["2N","4N"]})
    slots=t.prepare_native(run,"screen")
    check("screen_slot_count_uses24x2_plus_probes",len(slots)==40*2*(24+8*4)==4480)
    check("native_slots_longest_first",[p["harvest_time_days"] for p in slots]==sorted([p["harvest_time_days"] for p in slots],reverse=True))
    check("native_slots_indexed_without_fixed_slot_literals",[p["case_index"] for p in slots]==list(range(4480)))
    check("native_stage_relative_deadline_recorded",w.read(root/"screen/stage_identity.json")["relative_deadline_seconds"]==config["perspective"]["conditional"]["native_stage_deadline_seconds"]["screen"])
    t.verify_native_stage(run,"screen")
    check("native_support_manifest_verified",True)
    expect_failure("native_manifest_no_overwrite",lambda:t.prepare_native(run,"screen"),"already frozen")
    check("immutable_anchor_skips_refinement",t.refinement_eligibility(root,anchors[0])["status"]=="retained_immutable_anchor")
    c=selected[0];cid=c["id"];directory=root/"screen/analysis"/cid
    check("missing_screen_analysis_visible",t.refinement_eligibility(root,c)["reason"]=="missing_screen_summary")
    w.write(directory/"summary.json",{"failures":[{"reason":"synthetic_native_failure"}]})
    check("failed_native_support_skips_refinement",t.refinement_eligibility(root,c)["status"]=="skipped_incomplete_native_parent")
    w.write(directory/"summary.json",{"failures":[]});w.write(directory/"correction.json",{"source_x":c["x"]});w.write(directory/"microscopy_scores.json",{"total":3.,"native_minus_approximation_bias":None})
    check("unavailable_native_bias_skips_refinement",t.refinement_eligibility(root,c)["status"]=="skipped_invalid_native_microscopy")
    w.write(directory/"microscopy_scores.json",{"total":3.,"native_minus_approximation_bias":.25})
    check("finite_supported_refinement_is_eligible_without_quality_gate",t.refinement_eligibility(root,c)["eligible"] is True)
    x=np.asarray(c["x"]);wrong=x.copy();wrong[8]+=.01;w.write(directory/"correction.json",{"source_x":wrong.tolist()})
    check("mismatched_native_correction_source_blocks_refinement",t.refinement_eligibility(root,c)["reason"]=="correction_source_vector_mismatch")
    w.write(directory/"correction.json",{"source_x":c["x"]})
    records=[]
    for i,c in enumerate(selected[:8]):
        vector=np.asarray(c["x"]).copy();vector[8]+=i*.0001
        records.append({"id":"record_"+str(i),"source_id":"source_"+str(i),"selection_score":100.+i*.1,"x":vector.tolist()})
    records.append(dict(records[0],id="refined_same_source",selection_score=99.9))
    finalists,details=t.finalist_choice(records,config)
    check("finalists_deduplicate_source_before_two_best",finalists[0]["id"]=="refined_same_source" and finalists[1]["id"]=="record_1" and len({c["source_id"] for c in finalists})==3)
    unsupported=[dict(records[0]),dict(records[0],id="same_source_again")]
    expect_failure("insufficient_distinct_final_sources_explicit",lambda:t.finalist_choice(unsupported,config),"three supported distinct")
    fallback=[dict(record,selection_score=[1.,1.1,100.,101.][i]) for i,record in enumerate(records[:4])]
    _,details=t.finalist_choice(fallback,config)
    check("third_uses_source_defined_next_supported_fallback",details["third_fallback_to_next_supported"] is True)
    # Create source-like synthetic screen diagnostics, including one failed source.
    for i,c in enumerate(selected):
        directory=root/"screen/analysis"/c["id"]
        failure=[{"reason":"synthetic_failure"}] if i==0 else []
        w.write(directory/"summary.json",{"failures":failure})
        w.write(directory/"microscopy_scores.json",{"total":float(i+1),"native_minus_approximation_bias":.2})
        correction={"source_x":c["x"],"episode_ids":[p["episode_id"] for p in episodes],"delta_per_day":[0.]*len(episodes)}
        w.write(directory/"correction.json",correction)
        value=w.read(root/c["source"]);value.update(data_loss=float(i+1),assay_deviance=2.,ridge_penalty=.1,valid=True)
        w.write(directory/"corrected_final.json",value)
    finalists=t.select_finalists(run)
    check("full_finalist_manifest_has_three_sources",len(finalists)==3 and len({c["source_id"] for c in finalists})==3)
    audit=w.read(root/"audit/finalist_selection.json")
    check("failed_native_source_excluded_with_reason",any(e["id"]==selected[0]["id"] and e["reason"]=="unsupported_screen" for e in audit["excluded"]))
    final_slots=w.read(root/"final_validation/slots.json")
    check("independent_final_slots_all118x4_plus_probes",len(final_slots)==3*4*(118+8*4)==1800)
    check("final_validation_uses_four_configured_replicates",{p["replicate"] for p in final_slots}==set(range(4)))
    check("final_native_main_covers_all_observed_rows",set(i for p in final_slots if p["kind"]=="main" for i in p["observation_rows"])==set(range(343)))
    # Reports apply policy even with incomplete diagnostics, without adding work.
    before={str(p.relative_to(root)) for p in root.rglob("*")}
    report=w.report_run(run);acceptance=w.read(report.parent/"acceptance.json")
    check("accept_for_now_after_planned_validation_no_quality_threshold",acceptance["decision"]=="accept_for_now" and acceptance["validation_status"]=="incomplete" and acceptance["quality_threshold_applied"] is False)
    check("report_never_triggers_adaptive_followup",not acceptance["additional_correction"] and not acceptance["refit_triggered"] and not acceptance["additional_native_batch_triggered"] and before=={str(p.relative_to(root)) for p in root.rglob("*")})
    counts={"oxygen_values":sorted(data.dt),"episodes":len(episodes)}
    spec=s.campaign_spec(config,config_path,run,counts)
    plan=s.plan(spec,out/"scheduler",materialize=True)
    check("scheduler_complete18node_chain",len(plan["nodes"])==18 and plan["nodes"][-1]["name"]=="report_accept_for_now")
    check("scheduler_no_post_validation_adaptive_nodes",spec["post_validation_adaptive_nodes"]==[] and plan["post_validation_adaptive_nodes"]==[])
    byname={n["name"]:n for n in plan["nodes"]}
    check("scheduler_terminal_native_counts",byname["perspective_screen_native"]["tasks"]==4480 and byname["perspective_final_native"]["tasks"]==1800)
    check("scheduler_failed_native_diagnostics_and_report_still_run",byname["perspective_screen_diagnostics"]["condition"]=="afterany" and byname["perspective_final_diagnostics"]["condition"]=="afterany" and byname["report_accept_for_now"]["condition"]=="afterany")
    check("scheduler_cpu_throttle_has_resource_reason",any("--array=0-4479%1000"==v for v in byname["perspective_screen_native"]["submit_command"]) and not any("%" in v for v in byname["lineage_shared_stream"]["submit_command"] if v.startswith("--array")))
    manifest=byname["lineage_shared_stream"]["manifest_value"];groups=manifest["task_groups"];size=5
    check("stream_finalization_depends_on_own_fit",groups[size]["parent"]==0 and groups[size+1]["parent"]==1)
    first_sim=groups[2*size]
    argv,context=s.task_context(manifest,first_sim["first"]+1)
    check("stream_native_dispatches_current_candidate_and_local_trajectory",context["candidate_index"]==0 and context["trajectory_index"]==1 and argv[argv.index("--trajectory")+1]=="1")
    next_sim=groups[2*size+1];_,context=s.task_context(manifest,next_sim["first"])
    check("stream_next_candidate_trajectory_resets_to_zero",context["candidate_index"]==1 and context["trajectory_index"]==0)
    expect_failure("dispatcher_rejects_out_of_manifest_index",lambda:s.task_context(manifest,manifest["tasks"]),"outside")
    expect_failure("dispatcher_cannot_execute_under_setup_config",lambda:s.dispatch(byname["perspective_screen_native"]["manifest"],0),"authorized is false")
    expect_failure("submission_rejected_before_executor",lambda:s.submit(spec,out/"blocked_submit",executor=lambda argv:(_ for _ in ()).throw(AssertionError("Executor must not be called"))),"Submission disabled")
    check("dry_scheduler_plan_creates_no_jobs_record",not (out/"scheduler/jobs.json").exists() and plan["no_scheduler_calls"])
    # Exercise held-job setup/release and interrupted submission against a fake
    # executor only. The outer audit hook rejects every real process invocation.
    submit_config=copy.deepcopy(config)
    submit_config["execution"].update(authorized=True)
    submit_config["resources"].update(budget_cpu_hours_cap=9999.,scheduler_limits_verified=True)
    submit_config["test_only_authorization"]=True
    submit_config_path=out/"SYNTHETIC_AUTHORIZATION_ONLY.json";w.write(submit_config_path,submit_config)
    submit_run=w.prepare(submit_config,submit_config_path,"scheduler_synthetic_"+stamp)
    submit_spec=s.campaign_spec(submit_config,submit_config_path,submit_run,counts)
    calls=[];job_counter=[50000]
    def fake_executor(argv):
        calls.append(argv)
        if argv[0]=="sbatch":job_counter[0]+=1;return str(job_counter[0])
        return ""
    previous_slurm=os.environ.get("SLURM_JOB_ID")
    try:
        jobs=s.submit(submit_spec,out/"fake_submitted",executor=fake_executor)
        first_release=next(i for i,argv in enumerate(calls) if argv[:2]==["scontrol","release"])
        check("fake_scheduler_holds_entire_campaign_until_configured",len(jobs)==18 and sum(argv[0]=="sbatch" for argv in calls[:first_release])==18 and all("--hold" in argv for argv in calls if argv[0]=="sbatch"))
        check("fake_scheduler_replaces_all_symbolic_job_ids",not any("DRY_" in value for argv in calls for value in argv))
        check("fake_scheduler_releases_only_after_all_dependencies",len(calls[first_release:])==18 and all(argv[:2]==["scontrol","release"] for argv in calls[first_release:]))
        os.environ["SLURM_JOB_ID"]=jobs["report_accept_for_now"]
        raw="JobID|JobIDRaw|State|AllocCPUS|ElapsedRaw|TotalCPU|Submit|Eligible|Start|End|\n"
        job=jobs["lineage_shared_stream"]
        for jid,state,cpu in [(job,"COMPLETED","00:01:00"),(job+"_0","COMPLETED","00:00:30"),(job+"_5","FAILED","00:00:10"),(job+"_5.batch","FAILED","00:00:10"),(jobs["report_accept_for_now"],"RUNNING","00:00:01")]:
            raw += jid+"|9999|"+state+"|1|60|"+cpu+"|2026-10-16T00:00:00+00:00|2026-10-16T00:01:00+00:00|2026-10-16T00:02:00+00:00|"+("Unknown" if state=="RUNNING" else "2026-10-16T00:03:00+00:00")+"|\n"
        queried=[]
        usage=s.collect_accounting(submit_run,executor=lambda argv:(queried.append(argv) or raw))
        check("fake_accounting_maps_fit_finalize_and_excludes_parent_steps",set(usage["phases"])=={"lineage_shared_stream.fit","lineage_shared_stream.finalize","report_accept_for_now"} and usage["states"]=={"COMPLETED":1,"FAILED":1,"RUNNING":1})
        snapshot=w.read(submit_run/"report/accounting_snapshot.json")
        check("fake_accounting_labels_current_report_snapshot_partial",snapshot["nonterminal_rows"]==[jobs["report_accept_for_now"]] and usage["phases"]["report_accept_for_now"]["failed_or_cancelled_tasks"]==0 and len(queried)==1)
        task_manifest=out/"fake_submitted/verify_frozen_inputs_tasks.json"
        task_hash=w.sha(task_manifest)
        check("mock_dispatch_executes_only_input_validation",s.dispatch(task_manifest,0,task_hash)==0)
        original=w.read(task_manifest);mutated=copy.deepcopy(original);mutated["tasks"]=99;w.write(task_manifest,mutated)
        expect_failure("dispatcher_rejects_modified_task_manifest",lambda:s.dispatch(task_manifest,0,task_hash),"manifest changed")
        w.write(task_manifest,original)
        failure_calls=[]
        def failing_executor(argv):
            failure_calls.append(argv)
            if len(failure_calls)==2:raise RuntimeError("synthetic scheduler configuration failure")
            return "60000" if argv[0]=="sbatch" else ""
        try:s.submit(submit_spec,out/"fake_interrupted",executor=failing_executor)
        except RuntimeError:pass
        else:raise AssertionError("Expected fake scheduler failure")
        interrupted=w.read(out/"fake_interrupted/submission_status.json")
        check("fake_scheduler_failure_preserves_held_jobs_without_release",interrupted["status"]=="interrupted" and len(interrupted["jobs"])==1 and interrupted["released"]==[] and not any(argv[:2]==["scontrol","release"] for argv in failure_calls))
        expect_failure("partial_submission_cannot_be_resubmitted",lambda:s.submit(submit_spec,out/"fake_interrupted",executor=fake_executor),"Existing submitted")
    finally:
        if previous_slurm is None:os.environ.pop("SLURM_JOB_ID",None)
        else:os.environ["SLURM_JOB_ID"]=previous_slurm
    # Static source checks: copied numerical diagnostics are not evaluated.
    for name in ["native_diagnostics.py","native_refinement.py"]:
        text=(w.PACKAGE/"vendor"/name).read_text();tree=ast.parse(text)
        check("portable_source_no_absolute_campaign_dates_"+name,"datetime(2026" not in text and "hypothesis_tests/" not in text and "sbatch" not in text and "scontrol" not in text)
        check("portable_source_no_top_level_scientific_calls_"+name,not any(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) for n in tree.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=="insert")))
    w.write(out/"terminal_results.json",{"synthetic_run":str(run),"screen_candidates":40,"screen_native_slots":4480,"final_candidates":3,"final_native_slots":1800,"scheduler_nodes":len(plan["nodes"]),"scheduler_tasks":plan["total_array_tasks"],"models_evaluated":False,"native_engines_executed":False,"scheduler_contacted":False})
    screened_run=w.prepare(config,config_path,"screened_parent_synthetic_"+stamp)
    shared=w.read(screened_run/"lineage/shared_candidates.json")
    scores=[{"status":"complete","candidate":c,"x":c["initial"],"simulator_data_loss":10.+i*.1,"approximation_data_loss":10.+i*.2,"assumption_penalty":0.,"synthetic_not_scientific":True} for i,c in enumerate(shared[:3])]
    w.write(screened_run/"lineage/shared_scores.json",scores)
    w.write(screened_run/"lineage/shared_score_provenance.json",{"run_id":screened_run.name,"scores_sha256":w.sha(screened_run/"lineage/shared_scores.json"),"input_manifest_sha256":w.sha(screened_run/"input_manifest.json")})
    proposed=w.prepare_perspective(screened_run);proposals_hash=w.sha(screened_run/"perspective/candidates.json")
    finalized=w.prepare_perspective(screened_run,eligible_shared_ids=[shared[1]["id"],shared[2]["id"]],finalize_screened_pool=True)
    check("numerically_screened_parent_pool_can_finalize_before_fits",{c["parent"] for c in finalized}=={shared[1]["id"],shared[2]["id"]})
    check("screened_parent_finalization_preserves_initial_proposals",w.sha(screened_run/"perspective/initial_proposals_candidates.json")==proposals_hash)
