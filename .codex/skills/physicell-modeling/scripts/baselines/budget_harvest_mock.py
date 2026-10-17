"""Synthetic saved-evidence and compact-retention checks; no model/engine calls."""
from pathlib import Path
import copy
import hashlib
import json
import struct
import sys

import workflow as w
import budget_harvest as h


def run(out,stamp,check,expect_failure):
    import synthetic_data
    import terminal as t
    config=copy.deepcopy(w.load_config(w.DEFAULT_CONFIG));prepared=synthetic_data.build(out/"budget_synthetic_prepared")
    synthetic_data.configure(config,out,prepared,sys.executable)
    config["lineage"].update(shared_starts=3,ridge_starts_per_alpha=1,alphas=[0.])
    config["perspective"].update(starts_per_alpha=2)
    config_path=out/"budget_mock_config.json";w.write(config_path,config)
    config=w.load_config(config_path)
    def fixture(label):
        case=w.prepare(config,config_path,"budget_"+label+"_"+stamp)
        return case,w.read(case/"config.json")
    def lineage(case,index,kind="checkpoint",native=None,score=5.):
        candidate=w.read(case/"lineage/shared_candidates.json")[index];folder=case/"lineage/candidates"/candidate["id"]
        proof={"run_id":case.name,"candidate_id":candidate["id"],"candidate":candidate,"input_manifest_sha256":w.sha(case/"input_manifest.json")}
        w.write(folder/"attempt_identity.json",proof)
        value={"candidate":candidate,"x":candidate["initial"],"loss":score,"data_loss":score,"assumption_penalty":0.,"ridge_penalty":0.,"parameter_difference":0.,"synthetic_not_scientific":True}
        w.write(folder/"checkpoint.json",value)
        if kind=="final":
            w.write(folder/"final.json",value)
            w.write(folder/"final_provenance.json",dict(proof,final_sha256=w.sha(folder/"final.json"),checkpoint_sha256=w.sha(folder/"checkpoint.json")))
        if native:
            support={"requested_component_weight":[1.]*6,"supported_component_weight":[1. if native=="complete" else .5]*6,"component_weight_fraction":[1. if native=="complete" else .5]*6,"weight_fraction":1. if native=="complete" else .5,"mask":[[True]*6,[native=="complete"]*6],"missing_components":[]}
            files={name:w.sha(folder/name) for name in ["final.json","final_provenance.json","attempt_identity.json"]}
            record={"candidate":candidate,"x":value["x"],"status":native,"ranking_score":score,"native_support":{"replicates":[support],"requested_replicates":1},"score_evidence":{"candidate":candidate,"files":files}}
            record["simulator_data_loss" if native=="complete" else "partial_simulator_data_loss"]=score
            if native=="partial":record["simulator_data_loss"]=12345. # An inconsistent legacy full field must never become full evidence.
            w.write(folder/"score.json",record)
        return candidate,value,folder
    def perspective(case,kind="checkpoint",score=3.,candidate_id="perspective_0"):
        bounds=config["perspective"]["bounds"];x=[(a+b)/2 for a,b in bounds];x[:2]=[.2,.8]
        candidate={"id":candidate_id,"alpha":0.,"seed":123,"parent_run_id":case.name,"parent":"shared_0000","initial":x,"synthetic_not_scientific":True}
        root=case/"perspective";w.write(root/"candidates.json",[candidate]);w.write(root/"parents.json",{"parent_run_id":case.name,"shared":[]})
        folder=root/"candidates"/candidate["id"]
        w.write(folder/"attempt_identity.json",{"run_id":case.name,"candidate":candidate,"input_manifest_sha256":w.sha(case/"input_manifest.json")})
        episodes=w.read(case/"inputs/episodes.json")
        value={"valid":True,"candidate":candidate,"x":x,"loss":score,"data_loss":score-2.,"assay_deviance":2.,"ridge_penalty":0.,"assumption_penalty":0.,"seed_fractions":{p["episode_id"]:x[0 if p["founding_group"]=="2N" else 1] for p in episodes},"synthetic_not_scientific":True}
        w.write(folder/(kind+".json"),value)
        return candidate,value,folder
    def harvest(case,cfg):return h.harvest(case,cfg)
    case,cfg=fixture("before_any_fit");result=harvest(case,cfg)
    check("budget_before_fitting_reports_unavailable_without_fabricated_fit",result["status"]=="unavailable_no_valid_saved_fit" and result["selected_fit_count"]==0 and not (case/"perspective/finalists.json").exists())
    case,cfg=fixture("one_parent_checkpoint");candidate,_,_=lineage(case,0);result=harvest(case,cfg)
    selected=result["lineage"]["shared"]["selected"]
    check("budget_before_search_retains_one_saved_lineage_checkpoint",len(selected)==1 and selected[0]["checkpoint_recovery"] and selected[0]["native_microscopy_loss"] is None and result["perspective"]["selected"]==[])
    w.report_run(case);acceptance=w.read(case/"report/acceptance.json")
    check("lineage_saved_fit_never_claims_perspective_availability",acceptance["saved_lineage_fit_count"]==1 and not acceptance["saved_fit_available"] and not acceptance["terminal_fit_available"])
    check("budget_harvest_never_prepares_native_validation",not (case/"perspective/final_validation").exists() and result["scientific_calls"]==0 and result["new_native_batches"]==0)
    check("budget_harvest_is_idempotent",harvest(case,cfg)==result)
    changed_config=copy.deepcopy(cfg);changed_config["lineage"]["shared_starts"]+=1
    expect_failure("budget_harvest_requires_exact_frozen_configuration",lambda:harvest(case,changed_config),"configuration differs")
    snapshot=case/result["frozen_snapshots"][0]["path"];saved_snapshot=w.read(snapshot);saved_snapshot["record"]["selection_score"]=-1.;w.write(snapshot,saved_snapshot)
    expect_failure("budget_frozen_fit_snapshot_cannot_be_modified",lambda:harvest(case,cfg),"snapshot changed")
    case,cfg=fixture("full_vs_partial_native");lineage(case,0,"final","partial",.001);winner,_,_=lineage(case,1,"final","complete",100.);result=harvest(case,cfg)
    check("budget_full_native_precedes_artificially_small_partial_loss",result["lineage"]["shared"]["selected"][0]["id"]==winner["id"])
    check("budget_partial_native_keeps_missing_full_score_explicit",any(v["native_support"]=="partial" and v["native_microscopy_loss"] is None and v["partial_native_microscopy_loss"]==.001 for v in result["lineage"]["shared"]["ranking"]))
    native_case,native_config,native_result=case,cfg,result
    case,cfg=fixture("during_search");candidate,value,folder=perspective(case);result=harvest(case,cfg)
    chosen=result["perspective"]["selected"][0]
    check("budget_during_search_recovers_exact_evaluated_checkpoint",chosen["checkpoint_recovery"] and chosen["x"]==value["x"] and chosen["selection_score"]==value["loss"] and not (folder/"final.json").exists())
    w.report_run(case);acceptance=w.read(case/"report/acceptance.json")
    check("saved_perspective_fit_is_accepted_with_incomplete_validation",acceptance["saved_perspective_fit_count"]==1 and acceptance["decision"]=="accept_saved_fit_for_now" and not acceptance["full_scientific_completion"])
    check("budget_search_recovery_freezes_saved_source_and_input_identity",result["frozen_snapshots"] and w.read(case/result["frozen_snapshots"][0]["path"])["saved_source"]==value and chosen["input_manifest_sha256"]==w.sha(case/"input_manifest.json"))
    case,cfg=fixture("saved_parent_embedding")
    bounds=config["perspective"]["bounds"];x=[(a+b)/2 for a,b in bounds];x[:2]=[.2,.8]
    parent={"id":"shared_0000","x":x,"run_id":case.name,"reference":{}}
    w.write(case/"perspective/parents.json",{"parent_run_id":case.name,"shared":[parent]})
    evaluation={"valid":True,"loss":5.,"data_loss":3.,"assay_deviance":2.,"ridge_penalty":0.,"assumption_penalty":0.,"synthetic_not_scientific":True}
    w.write(case/"perspective/embedding_checks/0.json",{"parent":parent["id"],"parent_sha256":hashlib.sha256(json.dumps(parent,sort_keys=True,allow_nan=False).encode()).hexdigest(),"valid":True,"evaluation":evaluation})
    result=harvest(case,cfg)
    check("budget_before_search_retains_only_actual_saved_parent_evaluation",len(result["perspective"]["selected"])==1 and result["perspective"]["selected"][0]["stage"]=="exact_saved_parent_embedding" and result["perspective"]["selected"][0]["native_support"]=="unavailable")
    case,cfg=fixture("during_refinement");candidate,value,folder=perspective(case,"final",25.)
    root=case/"perspective";cid=candidate["id"];screen={"id":cid,"alpha":0.,"x":value["x"],"source":"candidates/"+cid+"/final.json","source_sha256":w.sha(folder/"final.json")}
    w.write(root/"screen_candidates.json",[screen]);t.prepare_native(case,"screen")
    analysis=root/"screen/analysis"/cid;correction={"status":"available","source_x":value["x"],"source_sha256":w.sha(root/"screen/frozen"/cid/"final.json"),"episode_ids":[p["episode_id"] for p in w.read(case/"inputs/episodes.json")],"delta_per_day":[0.]*118}
    w.write(analysis/"summary.json",{"status":"partial","failures":[{"reason":"synthetic_missing_case"}],"correction_status":"available"});w.write(analysis/"correction.json",correction)
    w.write(analysis/"microscopy_scores.json",{"total":None,"ranking_total":10.,"partial_total":10.,"ranking_native_minus_approximation_bias":.5,"native_support":[],"requested_replicates":2})
    w.write(analysis/"corrected_final.json",value)
    label="refined_"+cid+"_r000";attempt={"candidate_id":label,"source_candidate_id":cid,"refinement_replicate":0,"source_final_sha256":w.sha(folder/"final.json"),"correction_sha256":w.sha(analysis/"correction.json"),"source_x":value["x"],"lower_z":[0.]*32,"upper_z":[1.]*32}
    saved=dict(value,candidate={"id":label},source_candidate_id=cid,refinement_replicate=0,source_x=value["x"],source_final_sha256=attempt["source_final_sha256"],correction_sha256=attempt["correction_sha256"],data_loss=3.,loss=5.)
    w.write(root/"refinement"/cid/"replicate_000/attempt_identity.json",attempt);w.write(root/"refinement"/cid/"replicate_000/checkpoint.json",saved)
    result=harvest(case,cfg);chosen=result["perspective"]["selected"][0]
    check("budget_partial_native_refinement_checkpoint_is_retained_with_true_support",chosen["id"]==label and chosen["checkpoint_recovery"] and chosen["native_support"]=="partial" and chosen["native_screen_microscopy"] is None and chosen["selection_score"]==5.5)
    check("budget_refinement_preserves_full_support_provenance_snapshot",bool(w.read(case/result["frozen_snapshots"][0]["path"])["saved_support_evidence"]) and not (root/"finalists.json").exists())
    case,cfg=fixture("frozen_finalists");candidate,value,folder=perspective(case,"final")
    original=[{"id":candidate["id"],"source_id":candidate["id"],"alpha":0.,"x":value["x"],"source":"candidates/"+candidate["id"]+"/final.json","source_sha256":w.sha(folder/"final.json"),"selection_score":3.,"ranking_basis":"approximation_source_loss","native_support":"unavailable"}]
    w.write(case/"perspective/finalists.json",original);before=(case/"perspective/finalists.json").read_bytes();result=harvest(case,cfg)
    check("budget_existing_finalists_remain_byte_for_byte_frozen",result["perspective"]["existing_finalists_preserved"] and (case/"perspective/finalists.json").read_bytes()==before)
    case,cfg=fixture("frozen_finalist_foreign_attempt");candidate,value,folder=perspective(case,"final")
    frozen=[{"id":candidate["id"],"source_id":candidate["id"],"alpha":0.,"x":value["x"],"source":"candidates/"+candidate["id"]+"/final.json","source_sha256":w.sha(folder/"final.json"),"selection_score":3.,"ranking_basis":"approximation_source_loss","native_support":"unavailable"}]
    w.write(case/"perspective/finalists.json",frozen);proof=w.read(folder/"attempt_identity.json");proof["run_id"]="foreign";w.write(folder/"attempt_identity.json",proof)
    expect_failure("budget_preserving_finalists_does_not_bypass_input_provenance",lambda:harvest(case,cfg),"foreign or modified")
    case,cfg=fixture("foreign_attempt");_,_,folder=perspective(case);proof=w.read(folder/"attempt_identity.json");proof["input_manifest_sha256"]="foreign";w.write(folder/"attempt_identity.json",proof)
    expect_failure("budget_checkpoint_cannot_bypass_current_input_identity",lambda:harvest(case,cfg),"foreign or modified")
    case,cfg=fixture("altered_native_checkpoint");_,_,folder=lineage(case,0,"final","complete")
    score=w.read(folder/"score.json");score["score_evidence"]["files"]["final.json"]="changed";w.write(folder/"score.json",score)
    expect_failure("budget_native_score_requires_matching_frozen_physical_vector",lambda:harvest(case,cfg),"checkpoint identity changed")
    case,cfg=fixture("invalid_checkpoint");_,value,folder=perspective(case);value["x"]=list(value["x"]);value["x"][8]=1e6;w.write(folder/"checkpoint.json",value);result=harvest(case,cfg)
    check("budget_invalid_model_checkpoint_is_unavailable_not_a_fabricated_fit",result["perspective"]["selected"]==[] and result["perspective"]["excluded"])
    case,cfg=fixture("unmanifested_candidate");(case/"perspective/candidates/old_unlisted").mkdir(parents=True);w.write(case/"perspective/candidates/old_unlisted/final.json",{"valid":True,"loss":-1e20,"x":[0.]*33});result=harvest(case,cfg)
    check("budget_never_recovers_unmanifested_or_historical_candidates",result["perspective"]["selected"]==[])
    # Compact full-precision fields are the sole deletable payload class.
    case,cfg,result=native_case,native_config,native_result;winner=result["lineage"]["shared"]["selected"][0]
    def asset(cid,slot,row,digest):
        folder=case/"lineage/candidates"/cid/"simulations"/slot;folder.mkdir(parents=True,exist_ok=True)
        path=folder/"field_frame_0000.bin";payload=b"synthetic_native_field_v1".ljust(64,b"\0")+struct.pack("<5d",1.123456789012345,2.,3.,4.,5.);path.write_bytes(payload)
        record={"path":str(path.relative_to(case)),"sha256":w.sha(path),"bytes":len(payload),"kind":h.FIELD_ASSET_KIND,"protocol_version":1,"candidate_id":cid,"run_id":case.name,"input_manifest_sha256":w.sha(case/"input_manifest.json"),"source_checkpoint_sha256":digest,"observation_row":row,"observation_rows":[row],"replicate":0,"stage":"shared","required_for_report":True}
        w.write(folder/"field_assets.json",{"assets":[record],"raw_fields_retained":False});return path,payload
    kept,payload=asset(winner["id"],"000",175,winner["source_sha256"]);excess,_=asset(winner["id"],"001",57,winner["source_sha256"]);loser,_=asset("shared_0000","000",57,w.sha(case/"lineage/candidates/shared_0000/final.json"))
    numeric=kept.parent/"observables.npz";numeric.write_bytes(b"synthetic numeric measurements, never prune")
    policy={"global_bytes":len(payload),"max_assets_per_candidate":1};plan=h.asset_retention_plan(case,result,policy)
    check("budget_field_retention_preserves_bounded_full_precision_acquisition_frame",plan["retained_assets"]==1 and plan["retained_bytes"]==len(payload) and kept.read_bytes()==payload and plan["precision"].startswith("Original full-precision"))
    released=[];outcome=h.prune_assets(case,plan,release_asset=released.append)
    check("budget_field_pruning_removes_only_verified_losing_or_excess_frames",kept.exists() and not excess.exists() and not loser.exists() and numeric.exists() and len(outcome["removed"])==2)
    check("budget_field_pruning_releases_exact_controller_reservation_tokens",set(released)=={hashlib.sha256(str(p.relative_to(case)).encode()).hexdigest() for p in [excess,loser]})
    check("budget_field_pruning_and_plan_are_idempotent",h.asset_retention_plan(case,result,policy)==plan and h.prune_assets(case,plan)["removed"]==[])
    manifest=kept.parent/"field_assets.json";manifest_bytes=manifest.read_bytes();tampered=w.read(manifest);tampered["assets"][0]["source_checkpoint_sha256"]="changed";w.write(manifest,tampered)
    expect_failure("budget_field_retention_manifest_identity_is_immutable",lambda:h.asset_retention_plan(case,result,policy),"manifest changed")
    manifest.write_bytes(manifest_bytes)
    kept.write_bytes(payload+b"changed")
    expect_failure("budget_retained_field_corruption_is_integrity_failure",lambda:h.asset_retention_plan(case,result,policy),"asset changed")
    w.write(out/"budget_harvest_results.json",{"saved_evidence_only":True,"scientific_calls":0,"native_engines_run":0,"scheduler_calls":0,"deadline_cases":["before_any_fit","before_search","during_search","during_refinement"],"compact_field_protocol":"five float64 columns; original precision retained"})
