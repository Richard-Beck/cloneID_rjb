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
    config["perspective"]["conditional"]["refinement_replicates"]=8
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
    check("scarce_screen_pool_retains_all_available_finite_sources",len(t.quality_diversity(pool,config))==9)
    poor=copy.deepcopy(pool);poor[-1]["final"]["loss"]=1e30
    check("finite_model_valid_poor_score_has_no_quality_cutoff",len(t.quality_diversity(poor,config))==9)
    check("empty_screen_pool_is_explicitly_empty",t.quality_diversity([],config)==[])
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
    expect_failure("mismatched_native_correction_source_blocks_refinement",lambda:t.refinement_eligibility(root,c),"Correction source vector mismatch")
    w.write(directory/"correction.json",{"source_x":c["x"]})
    w.write(directory/"summary.json",{"failures":[{"reason":"synthetic_missing_probe"}],"correction_status":"available"})
    w.write(directory/"microscopy_scores.json",{"total":None,"ranking_total":3.,"ranking_native_minus_approximation_bias":.25})
    check("supported_partial_native_bias_can_refine_without_quality_gate",t.refinement_eligibility(root,c)["eligible"] is True and t.refinement_eligibility(root,c)["native_support"]=="partial")
    records=[]
    for i,c in enumerate(selected[:8]):
        vector=np.asarray(c["x"]).copy();vector[8]+=i*.0001
        records.append({"id":"record_"+str(i),"source_id":"source_"+str(i),"selection_score":100.+i*.1,"x":vector.tolist()})
    records.append(dict(records[0],id="refined_same_source",selection_score=99.9))
    finalists,details=t.finalist_choice(records,config)
    check("finalists_deduplicate_source_before_two_best",finalists[0]["id"]=="refined_same_source" and finalists[1]["id"]=="record_1" and len({c["source_id"] for c in finalists})==3)
    unsupported=[dict(records[0]),dict(records[0],id="same_source_again")]
    scarce,scarce_details=t.finalist_choice(unsupported,config)
    check("insufficient_distinct_final_sources_retained_without_duplication",len(scarce)==1 and scarce_details["status"]=="degraded")
    empty,empty_details=t.finalist_choice([],config)
    check("empty_finalist_pool_records_unavailability",empty==[] and empty_details["status"]=="unavailable")
    for quota in [1,2]:
        quota_config=copy.deepcopy(config);quota_config["perspective"]["conditional"]["finalists"]=quota
        limited_finalists,limited_audit=t.finalist_choice(records,quota_config)
        check("configured_finalist_quota_"+str(quota)+"_never_exceeded",len(limited_finalists)==quota and limited_audit["requested_finalists"]==quota)
    fallback=[dict(record,selection_score=[1.,1.1,100.,101.][i]) for i,record in enumerate(records[:4])]
    _,details=t.finalist_choice(fallback,config)
    check("third_uses_source_defined_next_supported_fallback",details["third_fallback_to_next_supported"] is True)
    def evidence_record(label,score,support,components=None,fraction=None,mask=None):
        value=dict(records[0],id=label,source_id=label,selection_score=score,native_support=support,ranking_basis="native_corrected_composite" if support=="complete" else "native_partial_corrected_composite")
        if components is not None:value.update(native_requested_replicates=1,native_screen_indices=[0,1],native_support_detail=[{"requested_component_weight":[1.]*6,"supported_component_weight":components,"component_weight_fraction":components,"weight_fraction":fraction,"mask":mask,"missing_components":[i for i,v in enumerate(components) if not v]}])
        return value
    full=[evidence_record("full_"+str(i),100.+i,"complete") for i in range(3)]
    partial=evidence_record("partial_artificially_cheap",.001,"partial",[1.,1.,1.,1.,1.,0.],.9,[[True]*5+[False],[False]*6])
    tiered,tier_audit=t.finalist_choice(full+[partial],config)
    check("partial_missing_components_cannot_outrank_three_full_native_sources",all(q["native_support"]=="complete" for q in tiered) and tier_audit["evidence_groups"][0]["tier"]==0)
    complete_components=evidence_record("complete_components_low_coverage",1000.,"partial",[.1]*6,.1,[[True]*6,[False]*6])
    tiered,tier_audit=t.finalist_choice(full[:2]+[partial,complete_components],config)
    check("scarce_full_pool_fills_by_component_mass_before_partial_loss",tiered[-1]["id"]==complete_components["id"] and tier_audit["scarcity_filled_from_lower_support"] and tiered[-1]["ranking_component_mass"]==1.)
    pattern_a=evidence_record("partial_pattern_a",999.,"partial",[.5]*6,.5,[[True]*6,[False]*6])
    pattern_b=evidence_record("partial_pattern_b",.001,"partial",[.5]*6,.5,[[False]*6,[True]*6])
    tiered,tier_audit=t.finalist_choice(full[:2]+[pattern_b,pattern_a],config)
    check("different_partial_support_patterns_never_compete_by_loss",tiered[-1]["id"]==pattern_a["id"] and pattern_a["ranking_support_pattern"]!=pattern_b["ranking_support_pattern"])
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
    w.write(root/"refinement"/selected[1]["id"]/"outcome.json",{"status":"failed","reason":"synthetic_refinement_failure","scores_fabricated":False})
    refinement_source=selected[1];refinement_directory=root/"screen/analysis"/refinement_source["id"]
    for replica,data_loss in [(0,1.5),(1,.5)]:
        label="refined_"+refinement_source["id"]+f"_r{replica:03}";value=w.read(refinement_directory/"corrected_final.json")
        value.update(candidate={"id":label},source_candidate_id=refinement_source["id"],source_x=refinement_source["x"],source_final_sha256=w.sha(root/refinement_source["source"]),correction_sha256=w.sha(refinement_directory/"correction.json"),data_loss=data_loss,refinement_replicate=replica)
        w.write(root/"refinement"/refinement_source["id"]/f"replicate_{replica:03}"/"final.json",value)
        w.write(root/"refinement"/refinement_source["id"]/f"replicate_{replica:03}"/"attempt_identity.json",{"candidate_id":label,"source_candidate_id":refinement_source["id"],"refinement_replicate":replica,"source_final_sha256":value["source_final_sha256"],"correction_sha256":value["correction_sha256"],"source_x":refinement_source["x"]})
    finalists=t.select_finalists(run)
    check("full_finalist_manifest_has_three_sources",len(finalists)==3 and len({c["source_id"] for c in finalists})==3)
    audit=w.read(root/"audit/finalist_selection.json")
    check("partial_native_source_kept_with_explicit_limitation",any(e["id"]==selected[0]["id"] and e["native_support"]=="partial" for e in audit["limitations"]) and any(c["source_id"]==selected[0]["id"] and c["ranking_basis"]=="native_partial_corrected_composite" for c in w.read(root/"native_informed_ranking.json")))
    check("full_supported_corrected_score_numerics_unchanged",all(abs(c["selection_score"]-(c["corrected_cohort_microscopy"]+.2+2.+.1))<1e-12 for c in w.read(root/"native_informed_ranking.json")))
    check("bounded_refinement_replicas_compete_within_one_original_source",any(c["id"]=="refined_"+refinement_source["id"]+"_r001" and c["refinement_replicate"]==1 for c in finalists) and sum(c["source_id"]==refinement_source["id"] for c in finalists)==1)
    final_slots=w.read(root/"final_validation/slots.json")
    check("independent_final_slots_all118x4_plus_probes",len(final_slots)==3*4*(118+8*4)==1800)
    check("final_validation_uses_four_configured_replicates",{p["replicate"] for p in final_slots}==set(range(4)))
    check("final_native_main_covers_all_observed_rows",set(i for p in final_slots if p["kind"]=="main" for i in p["observation_rows"])==set(range(343)))
    # Reports apply policy even with incomplete diagnostics, without adding work.
    before={str(p.relative_to(root)) for p in root.rglob("*")}
    report=w.report_run(run);acceptance=w.read(report.parent/"acceptance.json")
    check("accept_for_now_after_planned_validation_no_quality_threshold",acceptance["decision"]=="accept_for_now" and acceptance["validation_status"]=="incomplete" and acceptance["quality_threshold_applied"] is False)
    check("report_never_triggers_adaptive_followup",not acceptance["additional_correction"] and not acceptance["refit_triggered"] and not acceptance["additional_native_batch_triggered"] and before=={str(p.relative_to(root)) for p in root.rglob("*")})
    # Scarcity paths cross selection, frozen native manifests and reporting using
    # saved synthetic results only. No fitter, native engine or scheduler runs.
    def fixture(label,indices=(),parent_count=0,invalid=False):
        case=w.prepare(config,config_path,label+"_"+stamp);case_root=case/"perspective"
        manifest=copy.deepcopy(w.read(root/"parents.json"));manifest["shared"]=manifest["shared"][:parent_count];manifest["parent_run_id"]=case.name
        for p in manifest["shared"]:p["run_id"]=case.name
        w.write(case_root/"parents.json",manifest);proposals=[]
        for i in indices:
            proposal=copy.deepcopy(candidates[i]);proposal["parent_run_id"]=case.name;proposals.append(proposal)
            value=copy.deepcopy(w.read(root/"candidates"/proposal["id"]/"final.json"));value["valid"]=not invalid
            w.write(case_root/"candidates"/proposal["id"]/"final.json",value)
        w.write(case_root/"candidates.json",proposals)
        return case,case_root
    anchor_run,anchor_root=fixture("one_anchor_no_exploratory_finals",parent_count=1)
    scarce_selected=t.select_screen(anchor_run);scarce_slots=t.prepare_native(anchor_run,"screen")
    check("one_valid_anchor_survives_zero_exploratory_finals",len(scarce_selected)==1 and scarce_selected[0]["id"].startswith("anchor_") and w.read(anchor_root/"audit/screen_selection.json")["status"]=="degraded")
    check("scarce_native_manifest_uses_actual_candidate_count",len(scarce_slots)==112 and w.read(anchor_root/"screen/contract.json")["candidates"]==1)
    scarce_finalists=t.select_finalists(anchor_run)
    check("missing_native_analysis_falls_back_to_saved_source_score",len(scarce_finalists)==1 and scarce_finalists[0]["ranking_basis"]=="approximation_source_loss" and scarce_finalists[0]["native_screen_microscopy"] is None and scarce_finalists[0]["correction"] is None)
    check("one_finalist_has_independent_dynamic_validation_manifest",len(w.read(anchor_root/"final_validation/slots.json"))==600 and w.read(anchor_root/"final_validation/contract.json")["status"]=="degraded")
    scarce_report=w.report_run(anchor_run)
    check("scarce_saved_result_reaches_accept_for_now_report",w.read(scarce_report.parent/"acceptance.json")["decision"]=="accept_for_now")
    empty_run,empty_root=fixture("all_model_invalid_terminal_sources",indices=[0],invalid=True)
    check("invalid_model_sources_never_reach_native_selection",t.select_screen(empty_run)==[])
    check("empty_screen_still_freezes_zero_case_native_stage",t.prepare_native(empty_run,"screen")==[] and w.read(empty_root/"screen/contract.json")["status"]=="unavailable")
    check("empty_finalist_stage_freezes_without_fabricated_scores",t.select_finalists(empty_run)==[] and w.read(empty_root/"final_validation/slots.json")==[] and w.read(empty_root/"audit/finalist_selection.json")["status"]=="unavailable")
    empty_report=w.report_run(empty_run)
    check("empty_terminal_evidence_still_reaches_saved_report",empty_report.is_file() and w.read(empty_report.parent/"acceptance.json")["decision"]!="accept_for_now")
    partial_run,partial_root=fixture("partial_native_missing_correction",indices=[0,1])
    partial_selected=t.select_screen(partial_run);t.prepare_native(partial_run,"screen")
    first=partial_selected[0];analysis=partial_root/"screen/analysis"/first["id"]
    w.write(analysis/"summary.json",{"status":"partial","failures":[{"reason":"synthetic_timeout"}],"correction_status":"unavailable"})
    w.write(analysis/"microscopy_scores.json",{"total":None,"partial_total":5.,"ranking_total":5.,"ranking_basis":"native_partial_normalized","support":{"completed_rows":1,"requested_rows":24}})
    w.write(partial_root/"refinement"/first["id"]/"outcome.json",{"status":"failed","reason":"synthetic_failure"})
    partial_finalists=t.select_finalists(partial_run)
    check("finite_partial_native_evidence_survives_failed_refinement_and_missing_correction",len(partial_finalists)==1 and partial_finalists[0]["ranking_basis"]=="native_partial_uncorrected_composite" and partial_finalists[0]["native_support"]=="partial" and partial_finalists[0]["correction"] is None and partial_finalists[0]["selection_score"]==7.)
    check("native_and_approximation_scores_not_mixed_to_fill_finalist_quota",not w.read(partial_root/"audit/finalist_selection.json")["approximation_fallback_used"] and len(w.read(partial_root/"approximation_fallback_ranking.json"))==2)
    approximation_run,approximation_root=fixture("three_approximation_only_finalists",indices=[0,1,2])
    t.select_screen(approximation_run);t.prepare_native(approximation_run,"screen")
    approximation_finalists=t.select_finalists(approximation_run)
    check("all_missing_native_support_uses_finite_source_ranking_without_inventing_native_scores",len(approximation_finalists)==3 and all(q["ranking_basis"]=="approximation_source_loss" and q["native_ranking_microscopy"] is None for q in approximation_finalists))
    changed_run,changed_root=fixture("changed_selected_source",indices=[0])
    changed=t.select_screen(changed_run);t.prepare_native(changed_run,"screen")
    changed_path=changed_root/changed[0]["source"];changed_value=w.read(changed_path);changed_value["loss"]+=1.;w.write(changed_path,changed_value)
    expect_failure("scarcity_never_bypasses_selected_source_integrity",lambda:t.select_finalists(changed_run),"Selected native source changed")
    mismatch_run,mismatch_root=fixture("mismatched_terminal_correction",indices=[0])
    mismatch=t.select_screen(mismatch_run);t.prepare_native(mismatch_run,"screen")
    wrong=np.asarray(mismatch[0]["x"]).copy();wrong[8]+=.01
    w.write(mismatch_root/"screen/analysis"/mismatch[0]["id"]/"correction.json",{"source_x":wrong.tolist()})
    expect_failure("approximation_fallback_never_bypasses_correction_integrity",lambda:t.select_finalists(mismatch_run),"Correction source vector mismatch")
    replica_run,replica_root=fixture("refinement_replica_hash_mismatch",indices=[0])
    replica_selected=t.select_screen(replica_run);t.prepare_native(replica_run,"screen");candidate=replica_selected[0];cid=candidate["id"];analysis=replica_root/"screen/analysis"/cid
    w.write(analysis/"summary.json",{"failures":[],"correction_status":"available"});w.write(analysis/"correction.json",{"source_x":candidate["x"]});w.write(analysis/"microscopy_scores.json",{"total":3.,"native_minus_approximation_bias":.2})
    value=w.read(replica_root/candidate["source"]);value.update(candidate={"id":"refined_"+cid+"_r000"},source_candidate_id=cid,source_x=candidate["x"],source_final_sha256="changed",correction_sha256=w.sha(analysis/"correction.json"))
    w.write(replica_root/"refinement"/cid/"replicate_000/final.json",value)
    expect_failure("refinement_replica_provenance_cannot_degrade_past_hash_mismatch",lambda:t.select_finalists(replica_run),"Refinement source final changed")
    checkpoint_run,checkpoint_root=fixture("interrupted_refinement_checkpoint",indices=[0])
    checkpoint_selected=t.select_screen(checkpoint_run);t.prepare_native(checkpoint_run,"screen");candidate=checkpoint_selected[0];cid=candidate["id"];analysis=checkpoint_root/"screen/analysis"/cid
    w.write(analysis/"summary.json",{"failures":[],"correction_status":"available"});w.write(analysis/"correction.json",{"source_x":candidate["x"]});w.write(analysis/"microscopy_scores.json",{"total":3.,"native_minus_approximation_bias":.2})
    label="refined_"+cid+"_r000";attempt={"candidate_id":label,"source_candidate_id":cid,"refinement_replicate":0,"source_final_sha256":w.sha(checkpoint_root/candidate["source"]),"correction_sha256":w.sha(analysis/"correction.json"),"source_x":candidate["x"],"lower_z":[0.]*32,"upper_z":[1.]*32}
    value=w.read(checkpoint_root/candidate["source"]);value.update(candidate={"id":label},source_candidate_id=cid,source_x=candidate["x"],source_final_sha256=attempt["source_final_sha256"],correction_sha256=attempt["correction_sha256"],refinement_replicate=0,optimization_complete=False)
    w.write(checkpoint_root/"refinement"/cid/"replicate_000/attempt_identity.json",attempt);w.write(checkpoint_root/"refinement"/cid/"replicate_000/checkpoint.json",value)
    recovered=t.select_finalists(checkpoint_run)
    check("late_refinement_timeout_retains_valid_checkpoint_without_new_calls",len(recovered)==1 and recovered[0]["checkpoint_recovery"] and recovered[0]["source"].endswith("checkpoint.json") and not (checkpoint_root/"refinement"/cid/"replicate_000/final.json").exists())
    class LimitedSupport:pass
    limited=LimitedSupport();limited.dt={20.5:1.};limited.episodes=[dict(episodes[0],oxygen=20.5,founding_group="2N",arm="C")]
    check("partial_episode_support_retains_available_passage",t.subset(limited,24)==limited.episodes)
    limited.episodes=[]
    check("empty_episode_support_is_explicit",t.subset(limited,24)==[])
    counts={"oxygen_values":sorted(data.dt),"episodes":len(episodes)}
    spec=s.campaign_spec(config,config_path,run,counts)
    plan=s.plan(spec,out/"scheduler",materialize=True)
    check("scheduler_complete19node_chain_with_embedding_reducer",len(plan["nodes"])==19 and plan["nodes"][-1]["name"]=="report_accept_for_now" and any(n["name"]=="perspective_embedding_reduce" for n in plan["nodes"]))
    check("scheduler_no_post_validation_adaptive_nodes",spec["post_validation_adaptive_nodes"]==[] and plan["post_validation_adaptive_nodes"]==[])
    byname={n["name"]:n for n in plan["nodes"]}
    check("scheduler_terminal_native_counts",byname["perspective_screen_native"]["tasks"]==4480 and byname["perspective_final_native"]["tasks"]==1800)
    check("scheduler_refinement_has_eight_reserved_slots_per_source",byname["perspective_bounded_refinement"]["tasks"]==320)
    refinement_manifest=byname["perspective_bounded_refinement"]["manifest_value"]
    _,first_replica=s.task_context(refinement_manifest,8);_,last_replica=s.task_context(refinement_manifest,15)
    check("scheduler_refinement_slots_identify_source_and_replica",first_replica["source_candidate_index"]==1 and first_replica["refinement_replicate"]==0 and last_replica["source_candidate_index"]==1 and last_replica["refinement_replicate"]==7)
    check("scheduler_failed_native_diagnostics_and_report_still_run",byname["perspective_screen_diagnostics"]["condition"]=="afterany" and byname["perspective_final_diagnostics"]["condition"]=="afterany" and byname["report_accept_for_now"]["condition"]=="afterany")
    check("scheduler_cpu_throttle_has_resource_reason",any("--array=0-4479%1000"==v for v in byname["perspective_screen_native"]["submit_command"]) and not any("%" in v for v in byname["lineage_shared_stream"]["submit_command"] if v.startswith("--array")))
    manifest=byname["lineage_shared_stream"]["manifest_value"];groups=manifest["task_groups"];size=5
    check("stream_finalization_depends_on_own_fit",groups[size]["parent"]==0 and groups[size+1]["parent"]==1)
    first_sim=groups[2*size]
    argv,context=s.task_context(manifest,first_sim.get("indices",list(range(first_sim["first"],first_sim["last"]+1)))[1])
    check("stream_native_dispatches_current_candidate_and_local_trajectory",context["candidate_index"]==0 and context["trajectory_index"]==1 and argv[argv.index("--trajectory")+1]=="1")
    next_sim=groups[2*size+1];_,context=s.task_context(manifest,next_sim.get("indices",[next_sim["first"]])[0])
    check("stream_next_candidate_trajectory_resets_to_zero",context["candidate_index"]==1 and context["trajectory_index"]==0)
    for stage in ["shared","ridge"]:
        node=byname["lineage_"+stage+"_stream"];stream_groups=node["manifest_value"]["task_groups"]
        score_groups=[g for g in stream_groups if g["phase"]=="score"]
        simulations={g["candidate"]:g.get("indices",list(range(g["first"],g["last"]+1))) for g in stream_groups if g["phase"]=="simulate"}
        check("stream_"+stage+"_score_waits_for_all_own_native_indices",len(score_groups)==len(simulations) and all(g["parents"]==simulations[g["candidate"]] for g in score_groups))
        check("stream_"+stage+"_task_count_includes_per_candidate_scores",node["tasks"]==3*len(simulations)+sum(map(len,simulations.values())))
        for group,recipe in zip(stream_groups,node["configuration_commands"]):
            if group["phase"]!="score":continue
            expected="afterany:"+":".join("DRY_"+node["name"]+"_"+str(i) for i in group["parents"])
            dependency=next(v.split("=",1)[1] for v in recipe if v.startswith("Dependency="))
            check("stream_"+stage+"_score_dependency_exact_all_native_"+str(group["candidate"]),expected in dependency.split(","))
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
        check("fake_scheduler_holds_entire_campaign_until_configured",len(jobs)==len(plan["nodes"]) and sum(argv[0]=="sbatch" for argv in calls[:first_release])==len(plan["nodes"]) and all("--hold" in argv for argv in calls if argv[0]=="sbatch"))
        check("fake_scheduler_replaces_all_symbolic_job_ids",not any("DRY_" in value for argv in calls for value in argv))
        check("fake_scheduler_releases_only_after_all_dependencies",len(calls[first_release:])==len(plan["nodes"]) and all(argv[:2]==["scontrol","release"] for argv in calls[first_release:]))
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
