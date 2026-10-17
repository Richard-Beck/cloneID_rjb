"""Synthetic orchestration checks. No scientific modules or subprocesses permitted."""
from pathlib import Path
import copy
import csv
import json
import os
import sys
import time

import workflow as w


def main(output=None):
    import numpy as np
    for name in ["BASELINES_PREPARED_DATA","BASELINES_OUTPUT_ROOT","BASELINES_SCRATCH_ROOT","BASELINES_LINEAGE_ENGINE","BASELINES_PERSPECTIVE_ENGINE","CELLSEGMENTATIONS_ROOT"]:os.environ.pop(name,None)
    started=time.monotonic()
    stamp=str(time.time_ns())
    out=Path(output or w.resolve(w.load_config(w.DEFAULT_CONFIG),"scratch_root")/"tests").resolve()/("mock_"+stamp)
    out.mkdir(parents=True,exist_ok=False)
    fixture=out/"prepared"
    fixture.mkdir()
    checks=[];blocked_process_events=[]
    def guard(event,args):
        if event in {"subprocess.Popen","os.system","os.posix_spawn","os.fork","os.exec"}:
            blocked_process_events.append(event)
            raise RuntimeError("Synthetic/dry-run validation forbids process execution: "+event)
        if event=="import" and args and str(args[0]).startswith(("lineage_model","perspective_model","perspective_search","wgd_colony","wgd_transfer","core.")):
            raise RuntimeError("Scientific module import prohibited in setup validation")
    sys.addaudithook(guard)
    def check(name,predicate):
        if not predicate:raise AssertionError(name)
        checks.append(name)
    def expect_failure(name,callback,contains):
        try:callback()
        except (w.SetupError,FileNotFoundError) as error:
            check(name,contains in str(error))
        else:raise AssertionError("Expected failure: "+name)
    def csv_write(path,rows):
        with path.open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    rows=[];episodes=[];fields=[];assays=[]
    for gi,group in enumerate(["2N","4N"]):
        for depth in range(2):
            index=len(rows);eid=f"synthetic_{group}_{depth}";parent=None if not depth else f"synthetic_{group}_0"
            rows.append({"episode_id":eid,"time_days":0.,"group":group,"oxygen":20.5,"count":100,"total_count":100,"live_count":90,"dead_count":10})
            episodes.append({"episode_id":eid,"parent_episode_id":parent,"parent_transfer_time_days":None if not depth else 1.,"founding_group":group,"arm":"common" if not depth else "C","oxygen":20.5,"observation_rows":[index],"observation_times_days":[0.],"duration_days":1.,"needed_times_days":[0.,1.],"children":[] if depth else [{"child_episode_id":f"synthetic_{group}_1","time_days":1.}]})
            for fi in range(2):fields.append({"row":index,"n_cells":100,"live_count":90,"dead_count":10})
        assays.append({"id":"synthetic_assay_"+group,"episode_id":f"synthetic_{group}_0","group":group,"k":gi+1,"n":10,"time_days":0.})
    observed=np.zeros((4,30));observed[:,0]=np.log1p(100);observed[:,1]=np.log1p(10)
    np.savez_compressed(fixture/"observations.npz",observed=observed,scales=np.ones((4,30)),weights=np.ones((4,6))/4)
    csv_write(fixture/"observations.csv",rows);csv_write(fixture/"field_measurements.csv",fields)
    w.write(fixture/"episodes.json",episodes);w.write(fixture/"assays.json",assays)
    w.write(fixture/"metadata.json",{"synthetic":True,"observed_order":["total","dead"]})
    config=copy.deepcopy(w.load_config(w.DEFAULT_CONFIG))
    import synthetic_data
    synthetic_data.configure(config,out,fixture,sys.executable)
    config["lineage"].update(shared_starts=5,ridge_starts_per_alpha=3,replicates=3,alphas=[0.,7.])
    config["lineage"]["native_pool"].update(shared=5,ridge_per_alpha=3)
    config["perspective"].update(starts_per_alpha=7,alphas=[0.,.5,8.])
    config["inputs"]["required"]=[p.name for p in sorted(fixture.iterdir())]
    config["inputs"]["prepared_hashes"]={p.name:w.sha(p) for p in sorted(fixture.iterdir())}
    config_path=out/"config.json";w.write(config_path,config)
    config=w.load_config(config_path)
    preflight=w.preflight(config,config_path)
    check("synthetic_preflight_valid",preflight["setup_valid"])
    check("preflight_rejects_execution",not preflight["execution_ready"])
    check("default_command_is_safe_dry_run",w.main(["--config",str(config_path),"--output",str(out/"default_dry_run")])==0)
    plan=w.dependency_plan(config,config_path,preflight)
    check("nondefault_counts_shared_trajectories",sum(next(n for n in plan["nodes"] if n["name"]=="lineage_shared_native")["trajectories_per_candidate"])==5*1*3)
    check("nondefault_counts_ridge_trajectories",sum(next(n for n in plan["nodes"] if n["name"]=="lineage_ridge_native")["trajectories_per_candidate"])==2*3*1*2*3)
    check("nondefault_counts_perspective_fits",plan["common_totals"]["perspective_new_search_fits"]==3*7)
    check("per_candidate_stream_commands_frozen",all(k in next(n for n in plan["nodes"] if n["name"]=="lineage_shared_fit") for k in ("fit","finalize")) and "simulate" in next(n for n in plan["nodes"] if n["name"]=="lineage_shared_native"))
    check("dependency_failure_boundary",next(n for n in plan["nodes"] if n["name"]=="lineage_shared_native_select")["condition"]=="afterany" and next(n for n in plan["nodes"] if n["name"]=="report_accept_for_now")["condition"]=="afterany")
    run=w.prepare(config,config_path,"synthetic_validation_"+stamp)
    candidates=w.read(run/"lineage/shared_candidates.json")
    check("fresh_stratified_starts_have_no_parent",len(candidates)==5 and all("parent" not in c for c in candidates))
    check("deterministic_stratified_design",np.array_equal(w.stratified(np.log(config["lineage"]["natural_bounds"]),5,123),w.stratified(np.log(config["lineage"]["natural_bounds"]),5,123)))
    expect_failure("existing_output_refused",lambda:w.prepare(config,config_path,run.name),"exists")
    expect_failure("escaping_output_name_refused",lambda:w.prepare(config,config_path,"../escape"),"single")
    check("missing_shared_ranking_uses_explicit_fresh_design",w.current_shared_parents(run,config)[0]["ranking_basis"]=="fresh_unfitted_initial")
    def save_scores(scores):
        w.write(run/"lineage/shared_scores.json",scores)
        w.write(run/"lineage/shared_score_provenance.json",{"run_id":run.name,"scores_sha256":w.sha(run/"lineage/shared_scores.json"),"input_manifest_sha256":w.sha(run/"input_manifest.json")})
    scores=[{"status":"complete","candidate":c,"x":c["initial"],"simulator_data_loss":10.+i*.1,"approximation_data_loss":10.+i*.2,"assumption_penalty":0.,"synthetic_not_scientific":True} for i,c in enumerate(candidates[:2])]
    scores.append({"status":"failed","candidate":candidates[2],"failed_slots":[0],"synthetic_not_scientific":True})
    save_scores([scores[2]])
    check("all_native_failures_keep_fresh_design_available",w.current_shared_parents(run,config)[0]["ranking_basis"]=="fresh_unfitted_initial")
    save_scores(scores[:1])
    check("one_shared_parent_is_usable",len(w.current_shared_parents(run,config))==1)
    save_scores(scores)
    provenance=w.read(run/"lineage/shared_score_provenance.json");provenance["run_id"]="foreign_run"
    w.write(run/"lineage/shared_score_provenance.json",provenance)
    expect_failure("foreign_run_parent_ranking_refused",lambda:w.prepare_perspective(run),"does not belong")
    save_scores(scores)
    ridge=w.prepare_ridge(run)
    check("ridge_count_configured",len(ridge)==2*3)
    perspective=w.prepare_perspective(run)
    check("perspective_count_configured",len(perspective)==3*7)
    check("perspective_only_new_run_parents",all(c["parent_run_id"]==run.name and c["parent"] in {p["candidate"]["id"] for p in scores[:2]} for c in perspective))
    check("half_best_remainder_other_for_odd_counts",all([c["parent"] for c in perspective[i*7:(i+1)*7]]==[candidates[0]["id"]]*3+[candidates[1]["id"]]*4 for i in range(3)))
    mapped=w.read(run/"perspective/parents.json")["shared"]
    for parent in mapped:
        x=np.asarray(parent["x"]);source=np.asarray(next(s["x"] for s in scores[:2] if s["candidate"]["id"]==parent["id"]))
        check("state13_mapping_"+parent["id"],np.array_equal(x[7:20],source[[0,1,2,3,6,7,8,9,10,11,12,13,14]]) and np.array_equal(x[7:20],x[20:33]))
        check("common_density_cluster_mapping_"+parent["id"],np.array_equal(x[5:7],source[4:6]) and x[3]==0 and x[4]==1)
    expect_failure("perspective_starts_cannot_be_overwritten",lambda:w.prepare_perspective(run),"already frozen")
    expect_failure("worker_science_gate_precedes_import",lambda:w.worker(config,config_path,run,"lineage-fit","shared",0,0),"authorized is false")
    report=w.report_run(run)
    check("offline_report_keeps_partial_status",report.is_file() and w.read(report.parent/"results.json")["complete_scientific_baseline"] is False)
    bad=copy.deepcopy(config);bad["paths"]["output_root"]=str(out.parent/"outside")
    w.write(out/"bad_config.json",bad)
    expect_failure("output_root_escape_refused",lambda:w.load_config(out/"bad_config.json"),"scratch_root")
    bad=copy.deepcopy(config);bad["observation"]["shape_columns"]=29
    w.write(out/"bad_schema.json",bad)
    expect_failure("legacy_29_column_schema_refused",lambda:w.load_config(out/"bad_schema.json"),"30-column")
    csv_write(out/"accounting.csv",[
        {"JobIDRaw":"1_0","Phase":"fit","State":"COMPLETED","AllocCPUS":1,"ElapsedRaw":60,"TotalCPU":"00:00:30","Submit":"2026-10-16T00:00:00+00:00","Eligible":"2026-10-16T00:01:00+00:00","Start":"2026-10-16T00:02:00+00:00","End":"2026-10-16T00:03:00+00:00"},
        {"JobIDRaw":"1_1","Phase":"simulate","State":"FAILED","AllocCPUS":2,"ElapsedRaw":120,"TotalCPU":"00:00:45","Submit":"2026-10-16T00:00:00+00:00","Eligible":"2026-10-16T00:02:00+00:00","Start":"2026-10-16T00:02:30+00:00","End":"2026-10-16T00:04:30+00:00"},
        {"JobIDRaw":"1_1.batch","Phase":"simulate","State":"FAILED","AllocCPUS":2,"ElapsedRaw":120,"TotalCPU":"00:00:45","Submit":"2026-10-16T00:00:00+00:00","Eligible":"2026-10-16T00:02:00+00:00","Start":"2026-10-16T00:02:30+00:00","End":"2026-10-16T00:04:30+00:00"}])
    usage=w.accounting(out/"accounting.csv",out/"accounting_result.json")
    check("accounting_includes_failure_without_step_double_count",usage["states"]=={"COMPLETED":1,"FAILED":1})
    check("accounting_measured_vs_allocated_cpu",abs(usage["measured_cpu_hours"]-75/3600)<1e-12 and abs(usage["allocated_cpu_hours"]-300/3600)<1e-12 and usage["peak_allocated_cpus"]==3)
    check("accounting_queue_dependency_elapsed_separated",usage["mean_eligible_to_start_queue_seconds"]==45 and usage["mean_submit_to_eligible_dependency_seconds"]==90 and usage["elapsed_first_start_to_last_end_seconds"]==150)
    import terminal_mock
    terminal_mock.run(out,stamp,check,expect_failure)
    import robust_mock
    robust_mock.run(out,stamp,config,check,expect_failure)
    import storage_aware_mock
    storage_aware_mock.run(out,stamp,config,check,expect_failure)
    import storage_ledger_mock
    storage_ledger_mock.run(out,config,check)
    import budget_harvest_mock
    budget_harvest_mock.run(out,stamp,check,expect_failure)
    import portability_checks
    portability_checks.run(out,check)
    check("no_scientific_modules_imported",not [name for name in sys.modules if name.startswith(("lineage_model","perspective_model","perspective_search","wgd_colony","wgd_transfer","core."))])
    check("no_process_or_scheduler_calls_attempted",blocked_process_events==[])
    report={"passed":True,"checks":checks,"check_count":len(checks),"synthetic_run":str(run),"fixture":str(fixture),"blocked_process_attempts":blocked_process_events,"scientific_model_imports":[],"scientific_model_calls":0,"fits_run":0,"simulations_run":0,"scheduler_calls":0,"elapsed_seconds":time.monotonic()-started,"time_utc":w.utc()}
    w.write(out/"results.json",report)
    w.write(out.parent/"mock_latest.json",report)
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
