"""Freeze useful saved evidence at a budget limit; never evaluate a model.

Only current-run JSON and declared compact field assets are read. Raw simulations,
historical runs, optimizer entrypoints and native engines are not dependencies.
"""
from pathlib import Path
import hashlib
import json
import math

import workflow as w


def _path(run,path):
    path=(Path(run)/path).resolve()
    if not w.inside(path,run):raise w.SetupError("Budget evidence outside this current run")
    return path


def _read(run,path):
    return w.read(_path(run,path))


def _finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _same_vector(left,right):
    return isinstance(left,list) and isinstance(right,list) and len(left)==len(right) and all(_finite(a) and _finite(b) and abs(a-b)<=1e-12 for a,b in zip(left,right))


def _candidate_path(run,family,cid,name):
    folder=_path(run,Path(family)/"candidates"/cid)
    if folder.parent!=_path(run,Path(family)/"candidates"):raise w.SetupError("Invalid budget candidate identity")
    return folder/name


def _attempt(run,candidate,path,identity):
    if not path.exists():return None
    proof=_read(run,path)
    if proof.get("run_id")!=identity["run_id"] or proof.get("candidate")!=candidate or proof.get("input_manifest_sha256")!=w.sha(run/"input_manifest.json"):
        raise w.SetupError("Budget fit attempt is foreign or modified")
    return proof


def _lineage_vector(value,stage,config):
    vector=value.get("x");size=15 if stage=="shared" else 30;bounds=config["lineage"]["natural_bounds"]
    return isinstance(vector,list) and len(vector)==size and all(_finite(v) and math.log(bounds[i%15][0])-1e-12<=v<=math.log(bounds[i%15][1])+1e-12 for i,v in enumerate(vector))


def _valid_saved(value,vector_ok):
    return not value.get("invalid",False) and value.get("valid") is not False and _finite(value.get("loss")) and vector_ok


def _record(run,candidate,path,value,family,stage,basis="approximation_source_loss"):
    return {"id":candidate["id"],"source_id":candidate["id"],"candidate_id":candidate["id"],"family":family,"stage":stage,"alpha":candidate.get("alpha",0.),"x":value["x"],"source":str(path.relative_to(run)),"source_sha256":w.sha(path),"selection_score":value["loss"],"ranking_basis":basis,"native_support":"unavailable","native_support_detail":None,"native_microscopy_loss":None,"approximation_data_loss":value.get("data_loss"),"assay_deviance":value.get("assay_deviance"),"ridge_penalty":value.get("ridge_penalty"),"assumption_penalty":value.get("assumption_penalty"),"checkpoint_recovery":path.name=="checkpoint.json","input_manifest_sha256":w.sha(run/"input_manifest.json"),"scores_fabricated":False}


def _ordered(records,config):
    import terminal
    groups={}
    for record in records:groups.setdefault(terminal.ranking_evidence(record,config),[]).append(record)
    ordered=[];seen=set()
    for key in sorted(groups,key=lambda k:(k[:3],min(v["source_id"] for v in groups[k]),k[3])):
        for value in sorted(groups[key],key=lambda v:(v["selection_score"],v["id"])):
            if value["source_id"] not in seen:ordered.append(value);seen.add(value["source_id"])
    return ordered


def _lineage(run,config,identity,stage,inputs):
    manifest=run/"lineage"/(stage+"_candidates.json");excluded=[];records=[]
    if not manifest.exists():return {"status":"unavailable","reason":"stage_not_prepared","selected":[],"ranking":[],"excluded":[]}
    candidates=_read(run,manifest);inputs[str(manifest.relative_to(run))]=w.sha(manifest)
    aggregate=run/"lineage"/(stage+"_scores.json");aggregate_scores={}
    if aggregate.exists():
        if stage=="shared":
            proof=run/"lineage/shared_score_provenance.json"
            if proof.exists():
                value=_read(run,proof)
                if value.get("run_id")!=identity["run_id"] or value.get("scores_sha256")!=w.sha(aggregate) or value.get("input_manifest_sha256")!=w.sha(run/"input_manifest.json"):raise w.SetupError("Budget shared score provenance changed")
            else:aggregate=None
        if aggregate is not None:aggregate_scores={v["candidate"]["id"]:v for v in _read(run,aggregate) if isinstance(v.get("candidate"),dict)}
    for candidate in candidates:
        cid=candidate["id"]
        if stage=="shared" and candidate.get("run_id")!=identity["run_id"] or stage!="shared" and candidate.get("parent_run_id")!=identity["run_id"]:raise w.SetupError("Foreign budget lineage candidate")
        folder=_candidate_path(run,"lineage",cid,"final.json").parent;attempt=folder/"attempt_identity.json"
        if _attempt(run,candidate,attempt,identity) is None:excluded.append({"id":cid,"reason":"missing_current_run_attempt"});continue
        inputs[str(attempt.relative_to(run))]=w.sha(attempt)
        proof_path=folder/"final_provenance.json";proof=_read(run,proof_path) if proof_path.exists() else None
        final=folder/"final.json"
        if proof is not None:
            if proof.get("run_id")!=identity["run_id"] or proof.get("candidate_id")!=cid or proof.get("input_manifest_sha256")!=w.sha(run/"input_manifest.json") or not final.exists() or proof.get("final_sha256")!=w.sha(final):raise w.SetupError("Budget lineage final provenance changed")
            checkpoint=folder/"checkpoint.json"
            if proof.get("checkpoint_sha256") and checkpoint.exists() and proof["checkpoint_sha256"]!=w.sha(checkpoint):raise w.SetupError("Budget lineage checkpoint changed")
            inputs[str(proof_path.relative_to(run))]=w.sha(proof_path)
        source=None;value=None
        for path in [final,folder/"checkpoint.json"]:
            if not path.exists():continue
            saved=_read(run,path)
            if saved.get("candidate") is not None and saved["candidate"]!=candidate:raise w.SetupError("Budget lineage source candidate changed")
            if _valid_saved(saved,_lineage_vector(saved,stage,config)):source=path;value=saved;break
            excluded.append({"id":cid,"source":str(path.relative_to(run)),"reason":"invalid_or_nonfinite_saved_fit"})
        if source is None:excluded.append({"id":cid,"reason":"no_valid_saved_final_or_checkpoint"});continue
        record=_record(run,candidate,source,value,"lineage",stage)
        score_path=folder/"score.json";score=_read(run,score_path) if score_path.exists() else aggregate_scores.get(cid)
        if score is not None:
            if score.get("candidate")!=candidate:raise w.SetupError("Budget lineage score candidate changed")
            evidence=score.get("score_evidence",{});files=evidence.get("files",{})
            if evidence and evidence.get("candidate")!=candidate:raise w.SetupError("Budget lineage score evidence changed")
            for name in ["final.json","attempt_identity.json","final_provenance.json","slots.json"]:
                if files.get(name) is not None and (not (folder/name).exists() or files[name]!=w.sha(folder/name)):raise w.SetupError("Budget lineage score checkpoint identity changed")
            if score.get("status") in {"complete","partial"}:
                if source!=final or proof is None or not files.get("final.json"):excluded.append({"id":cid,"reason":"native_score_missing_frozen_final_proof"})
                else:
                    if not _same_vector(score.get("x"),value["x"]):raise w.SetupError("Budget native score vector differs from final")
                    complete=score["status"]=="complete";field=("simulator_data_loss" if stage=="shared" else "simulator_penalized_loss") if complete else ("partial_simulator_data_loss" if stage=="shared" else "partial_simulator_penalized_loss")
                    number=score.get(field)
                    if _finite(number):
                        native=score.get("native_support",{})
                        if complete and isinstance(native,dict) and native.get("complete") is False:raise w.SetupError("Full native budget score has incomplete support")
                        if not complete and _finite(score.get("simulator_data_loss")):excluded.append({"id":cid,"reason":"full_native_score_ignored_for_partial_support"})
                        record.update(selection_score=number,ranking_basis="native_full_lineage" if complete else "native_partial_lineage",native_support="complete" if complete else "partial",native_support_detail=native.get("replicates") if isinstance(native,dict) else native,native_requested_replicates=native.get("requested_replicates") if isinstance(native,dict) else None,native_microscopy_loss=score.get("simulator_data_loss") if complete else None,partial_native_microscopy_loss=score.get("partial_simulator_data_loss") if not complete else None,native_score_source=str((score_path if score_path.exists() else aggregate).relative_to(run)),native_score_sha256=w.sha(score_path if score_path.exists() else aggregate),native_failures=score.get("failed_slots",[]))
                        inputs[record["native_score_source"]]=record["native_score_sha256"]
        inputs[str(source.relative_to(run))]=w.sha(source);records.append(record)
    ranking=_ordered(records,config)
    return {"status":"available" if ranking else "unavailable","selected":ranking[:1],"ranking":ranking,"excluded":excluded,"unavailable_native_evidence":sum(v["native_support"]=="unavailable" for v in records)}


def _perspective(run,config,identity,inputs):
    import terminal
    root=run/"perspective";excluded=[];records=[];frozen=root/"finalists.json"
    if frozen.exists():
        finalists=_read(run,frozen);inputs[str(frozen.relative_to(run))]=w.sha(frozen)
        manifest=root/"candidates.json";known={c["id"]:c for c in _read(run,manifest)} if manifest.exists() else {}
        stage_proof=False
        for stage in ["screen","final_validation"]:
            if (root/stage/"support_manifest.json").exists():terminal.verify_native_stage(run,stage);stage_proof=True
        for candidate in finalists:
            source=terminal.selected_source(root,candidate)
            if not source.exists():raise w.SetupError("Frozen budget finalist source is missing")
            value=_read(run,source)
            if not value.get("valid") or not terminal.valid_vector(value.get("x"),config) or not _same_vector(candidate.get("x"),value.get("x")):raise w.SetupError("Frozen budget finalist source invalid or modified")
            original=known.get(candidate.get("source_id",candidate["id"]))
            if original is not None:
                if original.get("parent_run_id")!=identity["run_id"]:raise w.SetupError("Frozen budget finalist has a foreign parent")
                attempt=_candidate_path(run,"perspective",original["id"],"attempt_identity.json")
                if _attempt(run,original,attempt,identity) is None:raise w.SetupError("Frozen budget finalist lacks current-run input provenance")
                inputs[str(attempt.relative_to(run))]=w.sha(attempt)
            elif not stage_proof:raise w.SetupError("Frozen budget finalist lacks current-run input provenance")
            record=dict(candidate,family="perspective",stage="frozen_finalist",candidate_id=candidate["id"],source=str(source.relative_to(run)),source_sha256=w.sha(source),input_manifest_sha256=w.sha(run/"input_manifest.json"),scores_fabricated=False)
            records.append(record);inputs[str(source.relative_to(run))]=w.sha(source)
        return {"status":"available" if records else "unavailable","existing_finalists_preserved":True,"frozen_finalists_sha256":w.sha(frozen),"selected":records,"ranking":records,"excluded":[],"selection_rule":"Preserve the existing frozen finalist manifest exactly"}
    evidence=terminal.finalist_evidence(run)
    for value in evidence["native_records"]:
        if not (root/"screen/support_manifest.json").exists():excluded.append({"id":value["id"],"reason":"missing_native_stage_provenance"});continue
        record=dict(value,family="perspective",stage="saved_screen_or_refinement",candidate_id=value["id"],source="perspective/"+value["source"],input_manifest_sha256=w.sha(run/"input_manifest.json"),scores_fabricated=False)
        support_paths=[root/"screen/analysis"/value["source_id"]/name for name in ["summary.json","microscopy_scores.json","correction.json"]]
        support_paths+=[root/"screen/frozen"/value["source_id"]/"final.json",root/"screen/support_manifest.json"]
        if value.get("refinement_replicate") is not None:support_paths.append(_path(run,record["source"]).parent/"attempt_identity.json")
        record["native_evidence_files"]={str(p.relative_to(run)):w.sha(p) for p in support_paths if p.exists()}
        inputs.update(record["native_evidence_files"])
        records.append(record)
    excluded.extend(evidence["excluded"])
    manifest=root/"candidates.json";candidates=_read(run,manifest) if manifest.exists() else []
    if manifest.exists():inputs[str(manifest.relative_to(run))]=w.sha(manifest)
    for candidate in candidates:
        cid=candidate["id"]
        if candidate.get("parent_run_id")!=identity["run_id"]:raise w.SetupError("Foreign budget perspective parent")
        folder=_candidate_path(run,"perspective",cid,"final.json").parent;attempt=folder/"attempt_identity.json"
        if _attempt(run,candidate,attempt,identity) is None:excluded.append({"id":cid,"reason":"missing_current_run_attempt"});continue
        inputs[str(attempt.relative_to(run))]=w.sha(attempt)
        for path in [folder/"final.json",folder/"checkpoint.json",folder/"warmup.json"]:
            if not path.exists():continue
            value=_read(run,path)
            if value.get("candidate") is not None and value["candidate"]!=candidate:raise w.SetupError("Budget perspective source candidate changed")
            if not _valid_saved(value,bool(value.get("valid")) and terminal.valid_vector(value.get("x"),config)):
                excluded.append({"id":cid,"reason":"invalid_or_nonfinite_saved_fit","source":str(path.relative_to(run))});continue
            record=_record(run,candidate,path,value,"perspective","saved_exploration")
            if path.name=="warmup.json":record.update(stage="saved_warmup",evaluation_basis="actual_saved_warmup_evaluation")
            records.append(record);inputs[str(path.relative_to(run))]=w.sha(path);break
    # Numerical embedding checks contain actual evaluated objective/assay terms.
    # An unevaluated shared parameter mapping is never presented as a fit.
    parents_path=root/"parents.json"
    if parents_path.exists():
        parents=_read(run,parents_path)
        if parents.get("parent_run_id")!=identity["run_id"]:raise w.SetupError("Foreign budget parent embedding")
        completed=root/"embedding_check.json";completed_proof=_read(run,completed) if completed.exists() else None
        if completed_proof is not None:
            for name,key in [("parents.json","parents_sha256"),("candidates.json","candidates_sha256")]:
                if completed_proof.get(key) is not None and completed_proof[key]!=w.sha(root/name):raise w.SetupError("Budget embedding manifest changed")
        for index,parent in enumerate(parents.get("shared",[])+parents.get("fresh_fallback",[])):
            if parent.get("run_id")!=identity["run_id"]:raise w.SetupError("Foreign budget embedding parent")
            value=parent.get("embedding_result") if completed_proof is not None else None
            source=parents_path;member="shared/"+parent["id"]+"/embedding_result"
            check_path=root/"embedding_checks"/(str(index)+".json")
            if value is None and check_path.exists():
                checked=_read(run,check_path);expected=hashlib.sha256(json.dumps(parent,sort_keys=True,allow_nan=False).encode()).hexdigest()
                if checked.get("parent")!=parent["id"] or checked.get("parent_sha256")!=expected:raise w.SetupError("Budget saved embedding identity changed")
                if checked.get("valid"):value=checked.get("evaluation");source=check_path;member="evaluation"
            if not isinstance(value,dict) or not value.get("valid") or not _finite(value.get("loss")) or not terminal.valid_vector(parent.get("x"),config):continue
            if value.get("x") is not None and not _same_vector(value["x"],parent["x"]):raise w.SetupError("Budget saved embedding vector differs from parent")
            candidate={"id":"anchor_"+parent["id"],"alpha":0.};value=dict(value,x=parent["x"])
            record=_record(run,candidate,source,value,"perspective","exact_saved_parent_embedding")
            record.update(embedded_parent_id=parent["id"],source_member=member,evaluation_basis="actual_saved_parent_embedding",parameter_estimation="unchanged shared physical embedding")
            records.append(record);inputs[str(source.relative_to(run))]=w.sha(source)
    # Native evidence takes precedence. Approximation sources fill only when no
    # native-informed candidate exists, matching normal terminal selection.
    native=[v for v in records if v["native_support"] in {"complete","partial"}]
    pool=native or records
    selected,selection=terminal.finalist_choice(pool,config)
    ranking=_ordered(pool,config)
    return {"status":"available" if selected else "unavailable","existing_finalists_preserved":False,"selected":selected,"ranking":ranking,"excluded":excluded,"limitations":evidence["limitations"],"selection":selection,"approximation_fallback_used":not bool(native),"selection_rule":"Normal terminal evidence tiers and within-support selection applied to saved results only"}


def _freeze(run,result,inputs):
    snapshots=[]
    groups=[result["lineage"][stage]["selected"] for stage in ["shared","ridge"]]+[result["perspective"]["selected"]]
    for records in groups:
        for record in records:
            if Path(record["id"]).name!=record["id"] or record["id"] in {".",".."}:raise w.SetupError("Invalid budget snapshot candidate identity")
            source=_path(run,record["source"])
            if w.sha(source)!=record["source_sha256"]:raise w.SetupError("Budget source changed while harvesting")
            inputs[record["source"]]=record["source_sha256"]
            destination=_path(run,Path("budget_terminal")/record["family"]/record["id"]/"fit.json")
            value={"record":record,"saved_source":_read(run,source),"source_member":record.get("source_member"),"run_id":result["run_id"],"input_manifest_sha256":result["input_manifest_sha256"],"scientific_calls":0}
            evidence=dict(record.get("native_evidence_files",{}))
            if record.get("native_score_source"):evidence[record["native_score_source"]]=record["native_score_sha256"]
            value["saved_support_evidence"]={}
            for name,digest in evidence.items():
                path=_path(run,name)
                if not path.exists() or w.sha(path)!=digest:raise w.SetupError("Budget support evidence changed while freezing")
                value["saved_support_evidence"][name]=_read(run,path);inputs[name]=digest
            if destination.exists():
                if _read(run,destination)!=value:raise w.SetupError("Existing budget snapshot differs")
            else:w.write(destination,value)
            snapshots.append({"path":str(destination.relative_to(run)),"sha256":w.sha(destination)})
    return snapshots


def harvest(run,config):
    """Freeze best current-run saved fits; call after workers have been quiesced."""
    run,frozen,identity=w.run_check(run)
    if config!=frozen:raise w.SetupError("Budget harvest configuration differs from frozen run")
    destination=run/"budget_terminal.json"
    if destination.exists():
        result=_read(run,destination)
        if result.get("run_id")!=identity["run_id"] or result.get("input_manifest_sha256")!=w.sha(run/"input_manifest.json") or result.get("config_value_sha256")!=identity["config_value_sha256"] or result.get("package_manifest_sha256")!=identity["package_manifest_sha256"]:raise w.SetupError("Frozen budget terminal identity changed")
        for item in result.get("frozen_snapshots",[]):
            if w.sha(_path(run,item["path"]))!=item["sha256"]:raise w.SetupError("Frozen budget fit snapshot changed")
        for name,digest in result.get("saved_evidence_files",{}).items():
            if not _path(run,name).exists() or w.sha(_path(run,name))!=digest:raise w.SetupError("Frozen budget source evidence changed")
        return result
    inputs={};result={"schema_version":1,"run_id":identity["run_id"],"input_manifest_sha256":w.sha(run/"input_manifest.json"),"config_value_sha256":identity["config_value_sha256"],"package_manifest_sha256":identity["package_manifest_sha256"],"mode":"saved_evidence_budget_completion","scientific_calls":0,"new_fits":0,"new_native_batches":0,"scores_fabricated":False,"normal_finalists_written":False,"created_utc":w.utc()}
    result["lineage"]={stage:_lineage(run,frozen,identity,stage,inputs) for stage in ["shared","ridge"]}
    result["perspective"]=_perspective(run,frozen,identity,inputs)
    count=sum(len(v["selected"]) for v in result["lineage"].values())+len(result["perspective"]["selected"])
    result.update(status="available_saved_fits" if count else "unavailable_no_valid_saved_fit",selected_fit_count=count,unavailable_evidence={"lineage_shared":not bool(result["lineage"]["shared"]["selected"]),"lineage_ridge":not bool(result["lineage"]["ridge"]["selected"]),"perspective":not bool(result["perspective"]["selected"]),"independent_final_validation":"Read existing report evidence only; harvest schedules none"})
    result["frozen_snapshots"]=_freeze(run,result,inputs);result["saved_evidence_files"]=inputs
    w.write(destination,result)
    return result


FIELD_ASSET_KIND="native_cell_frame_v1"
RECOGNIZED_ROWS=[175,57,342,234]


def asset_retention_plan(run,terminal_result,policy=None):
    """Plan bounded full-precision field retention after candidate ranking.

    Producers write field_assets.json next to numeric case outcomes, outside raw
    case payload directories. Only their declared native_cell_frame_v1 .bin files
    can become pruning candidates. No numeric measurements or parameters qualify.
    """
    run,config,identity=w.run_check(run);policy=dict(policy or {})
    storage=config.get("storage",{})
    cap=int(policy.get("global_bytes",storage.get("figure_reservation_bytes",4_000_000_000)));per_candidate=int(policy.get("max_assets_per_candidate",4));per_asset=int(policy.get("max_asset_bytes",storage.get("frame_bytes",8_000_064)))
    if cap<0 or per_candidate<0 or per_asset<0:raise w.SetupError("Invalid field asset retention bounds")
    if terminal_result.get("run_id")!=identity["run_id"] or terminal_result.get("input_manifest_sha256")!=w.sha(run/"input_manifest.json"):raise w.SetupError("Foreign field retention selection")
    selection_hash=hashlib.sha256(json.dumps({"terminal":terminal_result,"lineage_path_sha256":w.sha(run/"lineage/results.json") if (run/"lineage/results.json").exists() else None},sort_keys=True,allow_nan=False).encode()).hexdigest()
    destination=run/"budget_terminal/retention_manifest.json"
    if destination.exists():
        previous=_read(run,destination)
        if previous.get("run_id")!=identity["run_id"] or previous.get("input_manifest_sha256")!=w.sha(run/"input_manifest.json") or previous.get("selection_sha256")!=selection_hash or previous.get("limits")!={"global_bytes":cap,"max_assets_per_candidate":per_candidate,"max_asset_bytes":per_asset}:raise w.SetupError("Field retention plan already frozen differently")
        for name,digest in previous["asset_manifests"].items():
            if not _path(run,name).exists() or w.sha(_path(run,name))!=digest:raise w.SetupError("Compact field manifest changed")
        for asset in previous["assets"]:
            path=_path(run,asset["path"])
            if asset["retention"]=="keep" and not path.exists():raise w.SetupError("Retained compact field asset missing")
            if path.exists() and (path.stat().st_size!=asset["bytes"] or w.sha(path)!=asset["sha256"]):raise w.SetupError("Compact field asset changed")
        return previous
    selected=terminal_result["lineage"]["shared"]["selected"]+terminal_result["lineage"]["ridge"]["selected"]+terminal_result["perspective"]["selected"]
    # Preserve each already-reported regularization-path winner for figure review.
    comparison=run/'lineage/results.json'
    if comparison.exists():
        byid={record['id']:record for stage in ('shared','ridge') for record in terminal_result['lineage'][stage].get('ranking',[])}
        for item in _read(run,comparison).get('ridge_path',[]):
            winner=item.get('winner') or {};cid=winner.get('candidate',{}).get('id')
            if cid in byid and byid[cid] not in selected:selected.append(byid[cid])
    priority={};allowed_hashes={}
    for rank,record in enumerate(selected):
        for cid in {record["id"],record.get("source_id",record["id"]),record.get("embedded_parent_id",record["id"])}:
            priority.setdefault(cid,rank);allowed_hashes.setdefault(cid,set()).add(record["source_sha256"])
    for stage in ["shared","ridge"]:
        for record in terminal_result["lineage"][stage].get("ranking",[]):
            if record["id"] in priority:allowed_hashes[record["id"]].add(record["source_sha256"])
    import terminal
    for stage in ["screen","final_validation"]:
        directory=run/"perspective"/stage
        if not (directory/"parameter_manifest.json").exists():continue
        if not (directory/"support_manifest.json").exists():continue
        terminal.verify_native_stage(run,stage)
        for cid,digest in _read(run,directory/"parameter_manifest.json").items():
            if cid not in priority:continue
            source=_path(run,directory/"frozen"/cid/"final.json")
            if not source.exists() or w.sha(source)!=digest:raise w.SetupError("Field asset frozen checkpoint changed")
            allowed_hashes[cid].add(digest)
    manifests=list(run.glob("lineage/candidates/*/simulations/*/field_assets.json"))
    for stage in ["screen","final_validation"]:manifests.extend(run.glob("perspective/"+stage+"/cases/*/*/field_assets.json"))
    assets=[];seen=set();manifest_hashes={}
    for manifest in sorted(manifests):
        manifest=_path(run,manifest);value=_read(run,manifest);manifest_hashes[str(manifest.relative_to(run))]=w.sha(manifest)
        for asset in value.get("assets",[]):
            path=_path(run,asset["path"])
            if path in seen:continue
            seen.add(path)
            if path.parent!=manifest.parent or path.suffix!=".bin" or not path.name.startswith("field_frame_") or asset.get("kind")!=FIELD_ASSET_KIND or asset.get("protocol_version")!=1:raise w.SetupError("Unsupported compact field pruning asset")
            if asset.get("run_id")!=identity["run_id"] or asset.get("input_manifest_sha256")!=w.sha(run/"input_manifest.json"):raise w.SetupError("Foreign compact field asset")
            if not path.exists():assets.append(dict(asset,retention="unavailable",reason="declared_asset_missing",manifest=str(manifest.relative_to(run))));continue
            if path.stat().st_size!=asset.get("bytes") or w.sha(path)!=asset.get("sha256"):raise w.SetupError("Compact field asset changed")
            cid=asset["candidate_id"];rows=asset.get("observation_rows",[asset.get("observation_row")]);recognized=[row for row in RECOGNIZED_ROWS if row in rows]
            reason=None
            if cid not in priority:reason="candidate_not_selected"
            elif asset.get("source_checkpoint_sha256") not in allowed_hashes[cid]:raise w.SetupError("Compact field source checkpoint differs from selected evidence")
            elif asset.get("replicate")!=0 or not recognized:reason="outside_recognized_acquisition_fields"
            elif asset["bytes"]>per_asset:reason="per_asset_byte_limit"
            assets.append(dict(asset,manifest=str(manifest.relative_to(run)),recognized_rows=recognized,retention="prune" if reason else "eligible",reason=reason))
    assets.sort(key=lambda a:(priority.get(a["candidate_id"],len(priority)),0 if a.get("stage")=="final_validation" else 1,min((RECOGNIZED_ROWS.index(row) for row in a.get("recognized_rows",[])),default=4),a["path"]))
    total=0;counts={};covered={}
    for asset in assets:
        if asset["retention"]!="eligible":continue
        cid=asset["candidate_id"];new_rows=set(asset["recognized_rows"])-covered.setdefault(cid,set())
        if not new_rows:reason="duplicate_acquisition_field"
        elif counts.get(cid,0)>=per_candidate:reason="per_candidate_asset_limit"
        elif total+asset["bytes"]>cap:reason="global_asset_byte_limit"
        else:reason=None
        asset.update(retention="prune" if reason else "keep",reason=reason)
        if reason is None:total+=asset["bytes"];counts[cid]=counts.get(cid,0)+1;covered[cid].update(new_rows)
    result={"schema_version":1,"run_id":identity["run_id"],"input_manifest_sha256":w.sha(run/"input_manifest.json"),"selection_sha256":selection_hash,"kind_allowlist":[FIELD_ASSET_KIND],"recognized_observation_rows":RECOGNIZED_ROWS,"replicate":0,"precision":"Original full-precision five-column float64 cell frame; no downsampling","limits":{"global_bytes":cap,"max_assets_per_candidate":per_candidate,"max_asset_bytes":per_asset},"retained_bytes":total,"retained_assets":sum(a["retention"]=="keep" for a in assets),"prunable_bytes":sum(a.get("bytes",0) for a in assets if a["retention"]=="prune"),"asset_manifests":manifest_hashes,"assets":assets,"raw_native_payloads_touched":False,"numeric_measurements_or_parameters_pruned":False}
    if destination.exists():
        previous=_read(run,destination)
        if previous!=result:raise w.SetupError("Field retention plan already frozen differently")
    else:w.write(destination,result)
    return result


def prune_assets(run,retention_manifest,release_asset=None):
    """Delete only hash-verified losing/excess declared compact field frames."""
    run,_,identity=w.run_check(run);frozen=run/"budget_terminal/retention_manifest.json"
    if not frozen.exists() or _read(run,frozen)!=retention_manifest:raise w.SetupError("Field pruning requires the exact frozen retention plan")
    if retention_manifest.get("run_id")!=identity["run_id"] or retention_manifest.get("input_manifest_sha256")!=w.sha(run/"input_manifest.json"):raise w.SetupError("Foreign field pruning plan")
    for name,digest in retention_manifest["asset_manifests"].items():
        if not _path(run,name).exists() or w.sha(_path(run,name))!=digest:raise w.SetupError("Compact field manifest changed before pruning")
    removed=[];already_missing=[];released=[]
    for asset in retention_manifest["assets"]:
        if asset["retention"]!="prune":continue
        path=_path(run,asset["path"]);manifest=_path(run,asset["manifest"])
        if asset.get("kind")!=FIELD_ASSET_KIND or asset.get("protocol_version")!=1 or path.suffix!=".bin" or not path.name.startswith("field_frame_") or path.parent!=manifest.parent:raise w.SetupError("Field pruning attempted outside compact frame allowlist")
        if not path.exists():already_missing.append(asset["path"])
        else:
            if path.stat().st_size!=asset["bytes"] or w.sha(path)!=asset["sha256"]:raise w.SetupError("Field asset changed before pruning")
            path.unlink();removed.append(asset["path"])
        if release_asset is not None:
            token=hashlib.sha256(str(path.relative_to(run)).encode()).hexdigest();release_asset(token);released.append(token)
    result={"run_id":identity["run_id"],"removed":removed,"already_missing":already_missing,"released_reservation_tokens":released,"removed_bytes":sum(a["bytes"] for a in retention_manifest["assets"] if a["path"] in removed),"numeric_measurements_or_parameters_pruned":False,"raw_native_payloads_touched":False}
    w.write(run/"budget_terminal/pruning_outcome.json",result)
    return result
