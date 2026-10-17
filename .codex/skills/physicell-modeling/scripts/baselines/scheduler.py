"""Pure scheduler planning and portable array dispatch; default never contacts SLURM."""
from pathlib import Path
import hashlib
import json
import os
import shlex

import workflow as w


def command(config,config_path,run,phase,stage=None,index=False,trajectory=False):
    argv=[str(w.resolve(config,"python")),str(w.PACKAGE/"workflow.py"),"worker","--config",str(Path(config_path).resolve()),"--run",str(Path(run).resolve()),"--phase",phase]
    if stage is not None:argv += ["--stage",stage]
    if index:argv += ["--index","<CANDIDATE_INDEX>"]
    if trajectory:argv += ["--trajectory","<TRAJECTORY_INDEX>"]
    return argv


def campaign_spec(config,config_path,run,prepared_counts):
    """Entire confirmed procedure. One chain shares a single resource cap."""
    l=config["lineage"];p=config["perspective"];c=p["conditional"];r=config["resources"]
    oxygen=len(prepared_counts["oxygen_values"]);episodes=prepared_counts["episodes"]
    nodes=[]
    def add(name,phase,tasks=1,stage=None,condition="afterok",minutes=None):
        argv=command(config,config_path,run,phase,stage,index=tasks>1)
        node={"name":name,"kind":"command","tasks":tasks,"minutes":minutes or r["report_wall_minutes"],"command":argv,"cwd":str(w.PACKAGE),"memory":str(r["memory_mb_per_task"])+"M","condition":condition}
        if nodes:node["depends_on"]=nodes[-1]["name"]
        nodes.append(node)
    def stream(stage,count,per_candidate):
        node={"name":"lineage_"+stage+"_stream","kind":"stream","trajectories_per_candidate":[per_candidate]*count,"cwd":str(w.PACKAGE),"memory":str(r["memory_mb_per_task"])+"M","depends_on":nodes[-1]["name"],"condition":"afterok"}
        preferred=l.get("native_oxygen_priority",[])
        slot_oxygen=[o for rep in range(l["replicates"]) for o in sorted(prepared_counts["oxygen_values"]) for group in (l["groups"] if stage=="ridge" else [None])]
        node["trajectory_priority"]=[preferred.index(o) if o in preferred else len(preferred) for o in slot_oxygen]
        for phase,minutes in [("fit",r["fit_wall_minutes"]),("finalize",r["finalize_wall_minutes"]),("simulate",r["native_wall_minutes"]),("score",r["report_wall_minutes"])]:
            worker_phase="lineage-score-candidate" if phase=="score" else "lineage-"+phase
            node[phase]={"command":command(config,config_path,run,worker_phase,stage,index=True,trajectory=phase=="simulate"),"minutes":minutes}
        nodes.append(node)
    add("verify_frozen_inputs","run-input-check")
    stream("shared",l["shared_starts"],oxygen*l["replicates"])
    add("lineage_shared_score","lineage-score",stage="shared",condition="afterany")
    add("lineage_ridge_prepare","lineage-ridge-prepare")
    stream("ridge",l["ridge_starts_per_alpha"]*len(l["alphas"]),oxygen*len(l["groups"])*l["replicates"])
    add("lineage_ridge_score","lineage-score",stage="ridge",condition="afterany")
    add("perspective_prepare","perspective-prepare")
    add("perspective_embedding","perspective-embedding-check",l["shared_starts"]+1,condition="afterany")
    add("perspective_embedding_reduce","perspective-embedding-finalize",condition="afterany")
    add("perspective_search","perspective-fit",p["starts_per_alpha"]*len(p["alphas"]),minutes=r["fit_wall_minutes"])
    add("perspective_screen_select","perspective-screen-select",condition="afterany")
    add("perspective_screen_prepare","perspective-native-prepare",stage="screen")
    selected=c["screen_candidates_per_alpha"]*len(p["alphas"])
    add("perspective_screen_native","perspective-native",selected*c["screen_replicates"]*(c["screen_passages"]+oxygen*len(c["minority_probe_fractions"])),stage="screen",minutes=r["native_wall_minutes"])
    add("perspective_screen_diagnostics","perspective-native-analyze",selected,stage="screen",condition="afterany")
    repeats=c.get("refinement_replicates",1)
    add("perspective_bounded_refinement","perspective-refine",selected*repeats,condition="afterany",minutes=r["fit_wall_minutes"])
    nodes[-1]["refinement_replicates"]=repeats
    add("perspective_finalist_select","perspective-finalist-select",condition="afterany")
    add("perspective_final_native","perspective-native",c["finalists"]*c["final_replicates"]*(episodes+oxygen*len(c["minority_probe_fractions"])),stage="final_validation",minutes=r["native_wall_minutes"])
    add("perspective_final_diagnostics","perspective-native-analyze",c["finalists"],stage="final_validation",condition="afterany")
    add("report_accept_for_now","report-accept",condition="afterany")
    return {"schema_version":1,"python":str(w.resolve(config,"python")),"max_cpus":r["max_concurrent_cpus"],"partition":r["partition"],"qos":r["qos"],"scientific_contract_confirmed":True,"execution_authorized":config["execution"]["authorized"],"config":str(Path(config_path).resolve()),"run":str(Path(run).resolve()),"nodes":nodes,"acceptance_policy":config["execution"]["acceptance_policy"],"post_validation_adaptive_nodes":[],"array_cap_reason":"Single agreed CPU envelope shared by fit/finalization/native work; sequential outer nodes prevent overlapping independently capped arrays"}


def task_groups(node):
    if node["kind"]!="stream":
        if "refinement_replicates" in node:
            repeats=node["refinement_replicates"]
            return [{"first":start,"last":start+repeats-1,"phase":"command","candidate":None,"parent":None,"source_candidate_index":start//repeats,"command":node["command"],"minutes":node["minutes"]} for start in range(0,node["tasks"],repeats)],node["tasks"]
        return [{"first":0,"last":node["tasks"]-1,"phase":"command","candidate":None,"parent":None,"command":node["command"],"minutes":node["minutes"]}],node["tasks"]
    counts=node["trajectories_per_candidate"];count=len(counts)
    if not counts or any(type(v) is not int or v<=0 for v in counts):raise w.SetupError("Positive frozen trajectory counts required")
    groups=[]
    for phase,offset,parent_offset in [("fit",0,None),("finalize",count,0)]:
        for i in range(count):groups.append({"first":offset+i,"last":offset+i,"phase":phase,"candidate":i,"parent":None if parent_offset is None else parent_offset+i,"command":node[phase]["command"],"minutes":node[phase]["minutes"]})
    cursor=2*count;native_ranges=[[] for _ in counts];local_slots=[[] for _ in counts]
    priority=node.get("trajectory_priority",[])
    ordered=sorted(((priority[slot] if slot<len(priority) else 0,slot,i) for i,native in enumerate(counts) for slot in range(native)))
    for _,slot,i in ordered:
        native_ranges[i].append(cursor);local_slots[i].append(slot);cursor+=1
    for i,indices in enumerate(native_ranges):
        groups.append({"first":min(indices),"last":max(indices),"indices":indices,"trajectory_indices":local_slots[i],"phase":"simulate","candidate":i,"parent":count+i,"command":node["simulate"]["command"],"minutes":node["simulate"]["minutes"]})
    for i,parents in enumerate(native_ranges):
        groups.append({"first":cursor,"last":cursor,"phase":"score","candidate":i,"parent":None,"parents":parents,"command":node["score"]["command"],"minutes":node["score"]["minutes"]});cursor+=1
    return groups,cursor


def task_context(manifest,index):
    """No subprocess, import of scientific models, or scheduler query."""
    for group in manifest["task_groups"]:
        if index in group["indices"] if "indices" in group else group["first"]<=index<=group["last"]:
            candidate=group["candidate"] if group["candidate"] is not None else index
            trajectory=group["trajectory_indices"][group["indices"].index(index)] if "indices" in group else index-group["first"]
            values={"<CANDIDATE_INDEX>":str(candidate),"<TRAJECTORY_INDEX>":str(trajectory)}
            argv=[values.get(value,value) for value in group["command"]]
            if any(value.startswith("<") and value.endswith(">") for value in argv):raise w.SetupError("Unresolved dispatcher placeholder")
            context={"candidate_index":candidate,"trajectory_index":trajectory if group["phase"]=="simulate" else None,"phase":group["phase"],"array_index":index}
            if "source_candidate_index" in group:context.update(source_candidate_index=group["source_candidate_index"],refinement_replicate=index-group["first"])
            return argv,context
    raise w.SetupError("Task index outside frozen scheduler manifest")


def plan(spec,out,materialize=True):
    """Materialize scripts, task tables and command recipes; NEVER submits."""
    out=Path(out).resolve()
    config=w.load_config(spec["config"])
    if not w.inside(out,w.resolve(config,"scratch_root")):raise w.SetupError("Scheduler plan must remain inside configured scratch_root")
    if (out/"jobs.json").exists():raise w.SetupError("Existing submitted campaign; do not overwrite or resubmit")
    if type(spec["max_cpus"]) is not int or spec["max_cpus"]<1:raise w.SetupError("Positive scheduler CPU envelope required")
    nodes=[];seen=[];recipes=[];jobs={}
    for node in spec["nodes"]:
        name=node["name"]
        if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in name) or name in seen:raise w.SetupError("Invalid/duplicate scheduler node")
        if node.get("depends_on")!=(seen[-1] if seen else None):raise w.SetupError("Outer scheduler nodes must form one CPU-capped chain")
        if node["condition"] not in {"afterok","afterany"}:raise w.SetupError("Unknown scheduler dependency condition")
        groups,count=task_groups(node);minutes=max(g["minutes"] for g in groups)
        manifest={"node":name,"kind":node["kind"],"run":spec["run"],"config":spec["config"],"task_groups":groups,"tasks":count,"package_manifest_sha256":w.sha(w.PACKAGE/"source_manifest.json")}
        manifest_path=out/(name+"_tasks.json");script=out/(name+".sh")
        expected_manifest_hash=hashlib.sha256((json.dumps(manifest,indent=2,sort_keys=True,allow_nan=False)+"\n").encode()).hexdigest()
        argv=[spec["python"],str(w.PACKAGE/"workflow.py"),"dispatch","--manifest",str(manifest_path),"--manifest-sha256",expected_manifest_hash]
        text="\n".join(["#!/bin/bash","set -euo pipefail","export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1","export SLURM_ARRAY_TASK_ID=${SLURM_ARRAY_TASK_ID:-0}","cd "+shlex.quote(node["cwd"]),"exec "+shlex.join(argv)])+"\n"
        submit=["sbatch","--parsable","--hold","--kill-on-invalid-dep=yes","--ntasks=1","--cpus-per-task=1","--mem="+node["memory"],"--time="+str(minutes),"--job-name=baseline_"+name,"--output="+str(out/(name+"_%A_%a.log"))]
        for key in ["partition","qos","account"]:
            if spec.get(key):submit.append("--"+key+"="+str(spec[key]))
        if count>1:submit.append("--array=0-"+str(count-1)+("%"+str(spec["max_cpus"]) if count>spec["max_cpus"] else ""))
        external=node["condition"]+":"+jobs[node["depends_on"]] if node.get("depends_on") else None
        if external:submit.append("--dependency="+external)
        submit.append(str(script));recipes.append(submit)
        job="DRY_"+name;jobs[name]=job;updates=[]
        if node["kind"]=="stream":
            for group in groups:
                selector="["+",".join(map(str,group["indices"]))+"]" if "indices" in group else str(group["first"]) if group["first"]==group["last"] else "["+str(group["first"])+"-"+str(group["last"])+"]"
                update=["scontrol","update","JobId="+job+"_"+selector,"TimeLimit="+str(group["minutes"])]
                deps=[external] if external else []
                if group["parent"] is not None:deps.append("afterany:"+job+"_"+str(group["parent"]))
                if group.get("parents"):deps.append("afterany:"+":".join(job+"_"+str(parent) for parent in group["parents"]))
                if deps:update.append("Dependency="+",".join(deps))
                updates.append(update);recipes.append(update)
        if materialize:
            out.mkdir(parents=True,exist_ok=True);w.write(manifest_path,manifest);script.write_text(text)
        nodes.append({"name":name,"tasks":count,"kind":node["kind"],"manifest":str(manifest_path),"manifest_value":manifest,"script":str(script),"submit_command":submit,"configuration_commands":updates,"depends_on":node.get("depends_on"),"condition":node["condition"]})
        seen.append(name)
    recipes += [["scontrol","release",job] for job in jobs.values()]
    result={"status":"dry_run","submitted":False,"nodes":nodes,"scheduler_commands":recipes,"total_array_tasks":sum(node["tasks"] for node in nodes),"max_array_tasks":max(node["tasks"] for node in nodes),"shared_cpu_cap":spec["max_cpus"],"acceptance_policy":spec["acceptance_policy"],"post_validation_adaptive_nodes":[],"no_scheduler_calls":True}
    if materialize:
        w.write(out/"specification.json",spec);w.write(out/"plan.json",result);w.write(out/"scheduler_commands.json",recipes)
    return result


def dispatch(manifest_path,index,expected_sha256=None):
    manifest=w.read(manifest_path);config=w.load_config(manifest["config"])
    w.execution_gate(config)  # Before any worker import or command execution.
    if expected_sha256 is not None and w.sha(manifest_path)!=expected_sha256:raise w.SetupError("Scheduler task manifest changed")
    if w.sha(w.PACKAGE/"source_manifest.json")!=manifest["package_manifest_sha256"]:raise w.SetupError("Dispatcher package identity changed")
    argv,context=task_context(manifest,index)
    run,_,_=w.run_check(manifest["run"],manifest["config"])
    # Dispatch in-process through the same parser/gates, preserving all accounting.
    w.write(run/"dispatch"/(manifest["node"]+"_"+str(index)+".json"),dict(context,node=manifest["node"],manifest_sha256=w.sha(manifest_path)))
    return w.main(argv[2:])


def trim_unused(run, active_counts, executor=None):
    """Cancel only never-needed reserved slots after an actual dynamic manifest exists.

    Normal preparation and mocks never contact the scheduler. During execution the
    preparation job is still an unmet parent, so downstream slots cannot have run.
    Every quota shortfall is recorded separately from failed scientific attempts.
    """
    run,config,_=w.run_check(run)
    submission=run/"scheduler_submission.json"
    if not config["execution"]["authorized"] or not os.environ.get("SLURM_JOB_ID") or not submission.exists():return {}
    w.execution_gate(config)
    saved=w.read(submission);plan=w.read(saved["plan_path"])
    nodes={node["name"]:node for node in plan["nodes"]};records={}
    if executor is None:
        import subprocess
        executor=lambda argv:subprocess.check_output(argv,text=True)
    for name,active in active_counts.items():
        if name not in nodes:raise w.SetupError("Unknown dynamic scheduler node: "+name)
        requested=nodes[name]["tasks"]
        if type(active) is not int or not 0<=active<=requested:raise w.SetupError("Dynamic task count exceeds frozen quota: "+name)
        record={"node":name,"active_tasks":active,"reserved_tasks":requested,"unused_tasks":requested-active,"reason":"unused_reserved_quota_after_manifest_preparation","time_utc":w.utc(),"scientific_failure":False}
        if active<requested:
            job=saved["jobs"][name]
            target=job if active==0 else job+"_["+str(active)+"-"+str(requested-1)+"]"
            record["command"]=["scancel",target]
            # Save the reason before the administrative cancellation.
            w.write(run/"scheduler/dynamic_counts"/(name+".json"),record)
            executor(record["command"])
        records[name]=record
        w.write(run/"scheduler/dynamic_counts"/(name+".json"),record)
    return records


def submit(spec,out,executor=None):
    """Future explicit launch, disabled by current config; never called by dry-run."""
    config=w.load_config(spec["config"])
    if not config["execution"]["authorized"]:
        raise w.SetupError("Submission disabled: no new execution/resource authorization")
    if not config["execution"]["perspective_source_accepted"]:raise w.SetupError("Scientific source not accepted")
    if not config["resources"].get("scheduler_limits_verified",False):raise w.SetupError("Verify target scheduler array/job limits before submission; no probe has been performed here")
    w.run_check(spec["run"],spec["config"])
    w.verify_runtime_dependencies(spec["run"])
    result=plan(spec,out,materialize=True)
    if executor is None:
        import subprocess
        executor=lambda argv:subprocess.check_output(argv,text=True)
    jobs={};released=[];operations=[]
    def mapped(argv):
        result=[]
        for value in argv:
            for name,job in sorted(jobs.items(),key=lambda item:-len(item[0])):
                value=value.replace("DRY_"+name,job)
            result.append(value)
        return result
    try:
        for node in result["nodes"]:
            argv=mapped(node["submit_command"]);operations.append(argv)
            job=str(executor(argv)).strip().split(";")[0]
            if not job.isdigit():raise w.SetupError("Unexpected scheduler response")
            jobs[node["name"]]=job;w.write(Path(out)/"jobs.json",jobs)
            for recipe in node["configuration_commands"]:
                argv=mapped(recipe);operations.append(argv);executor(argv)
        w.write(Path(spec["run"])/"scheduler_submission.json",{"root":str(Path(out).resolve()),"jobs":jobs,"plan_path":str((Path(out)/"plan.json").resolve()),"state":"held_and_configured"})
        for job in jobs.values():
            argv=["scontrol","release",job];operations.append(argv);executor(argv);released.append(job)
    except BaseException as error:
        w.write(Path(out)/"submission_status.json",{"status":"interrupted","jobs":jobs,"released":released,"error":repr(error),"recovery":"Inspect recorded held/released jobs; never automatically resubmit"})
        raise
    finally:w.write(Path(out)/"executed_scheduler_commands.json",operations)
    w.write(Path(out)/"submission_status.json",{"status":"released","jobs":jobs,"released":released})
    w.write(Path(spec["run"])/"scheduler_submission.json",{"root":str(Path(out).resolve()),"jobs":jobs,"plan_path":str((Path(out)/"plan.json").resolve()),"state":"released"})
    return jobs


def collect_accounting(run,executor=None):
    """Future authorized report-time sacct snapshot; injectable executor for mocks."""
    import csv
    import re
    run,config,_=w.run_check(run)
    w.execution_gate(config)
    submission=w.read(run/"scheduler_submission.json")
    plan=w.read(submission["plan_path"]);jobs=submission["jobs"]
    query=["sacct","-j",",".join(jobs.values()),"--format=JobID%80,JobIDRaw,State,AllocCPUS,ElapsedRaw,TotalCPU,Submit,Eligible,Start,End","-P"]
    if executor is None:
        import subprocess
        executor=lambda argv:subprocess.check_output(argv,text=True)
    raw=str(executor(query));output=run/"report";output.mkdir(exist_ok=True)
    (output/"slurm_accounting_snapshot.psv").write_text(raw)
    records=[row for row in csv.DictReader(raw.splitlines(),delimiter="|") if re.fullmatch(r"\d+(?:_\d+)?",row.get("JobID",""))]
    array_parents={row["JobID"].split("_")[0] for row in records if "_" in row["JobID"]}
    records=[row for row in records if row["JobID"] not in array_parents]
    node_by_job={str(jobs[node["name"]]):node for node in plan["nodes"]};normalized=[];unmapped=[]
    for row in records:
        jid=row["JobID"];parent=jid.split("_")[0];node=node_by_job.get(parent)
        if node is None:unmapped.append(jid);continue
        phase=node["name"]
        if node["kind"]=="stream":
            index=int(jid.split("_")[1]) if "_" in jid else 0
            _,context=task_context(node["manifest_value"],index);phase += "."+context["phase"]
        normalized.append({"JobIDRaw":jid,"Phase":phase,**{key:row.get(key,"") for key in ["State","AllocCPUS","ElapsedRaw","TotalCPU","Submit","Eligible","Start","End"]}})
    fields=["JobIDRaw","Phase","State","AllocCPUS","ElapsedRaw","TotalCPU","Submit","Eligible","Start","End"]
    path=output/"phase_task_accounting.csv"
    with path.open("w",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(normalized)
    snapshot={"query":query,"snapshot_utc":w.utc(),"records":len(normalized),"unmapped_job_ids":unmapped,"nonterminal_rows":[row["JobIDRaw"] for row in normalized if row["State"] not in {"COMPLETED","FAILED","CANCELLED","TIMEOUT","OUT_OF_MEMORY","NODE_FAIL","PREEMPTED","BOOT_FAIL","DEADLINE"}],"note":"Array parents and batch/extern steps excluded. Current reporting job can remain running; its allocation/CPU snapshot is partial, and its final local RUSAGE sidecar is written after report return. Raw native JobIDRaw remains in the .psv; normalized JobIDRaw uses logical array task IDs for phase mapping."}
    w.write(output/"accounting_snapshot.json",snapshot)
    if normalized:return w.accounting(path,output/"compute_usage.json")
    raise w.SetupError("Scheduler returned no attributable accounting rows; no compute totals fabricated")
