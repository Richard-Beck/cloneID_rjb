#!/usr/bin/env python3
"""Setup-only baseline entry point. Default: plan; never submits or runs science.

Scientific code is imported only by an explicitly gated worker operation. Planning,
preflight, input freezing, start construction, and synthetic tests do not import it.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import shutil
import sys
sys.dont_write_bytecode=True
import time
import traceback
from datetime import datetime, timezone

PACKAGE = Path(__file__).resolve().parent
DEFAULT_CONFIG = PACKAGE.parents[4]/"examples/sum159/baseline.json"
VERSION = 1
RUNTIME_COMMANDS = {
    "lineage-fit", "lineage-finalize", "lineage-simulate", "lineage-score", "lineage-score-candidate", "lineage-simulate-selected", "lineage-score-selected-candidate",
    "perspective-fit", "perspective-embedding-check",
    "perspective-native", "perspective-native-analyze", "perspective-refine",
}


class SetupError(RuntimeError):
    pass


def utc():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(2**20), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    tmp.replace(path)


def inside(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def resolve(config, key):
    value = config["paths"][key]
    if value is None:
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (Path(config["_config_dir"]) / path).resolve()


def load_config(path):
    config = read(path)
    config["_config_dir"]=str(Path(path).expanduser().resolve().parent)
    overrides={"prepared_data":"BASELINES_PREPARED_DATA","output_root":"BASELINES_OUTPUT_ROOT","scratch_root":"BASELINES_SCRATCH_ROOT","lineage_engine":"BASELINES_LINEAGE_ENGINE","perspective_engine":"BASELINES_PERSPECTIVE_ENGINE"}
    for key,env in overrides.items():
        if os.environ.get(env):config["paths"][key]=os.environ[env]
    if config["paths"].get("python") is None:config["paths"]["python"]=str(Path(sys.executable).resolve())
    if config.get("schema_version") != VERSION:
        raise SetupError("Unsupported configuration schema")
    for name in ("shared_starts", "ridge_starts_per_alpha", "replicates", "steps"):
        value = config["lineage"][name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise SetupError("Positive integer required: lineage." + name)
    for name in ("starts_per_alpha", "minimum_competitive_shared_parents", "steps"):
        value = config["perspective"][name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise SetupError("Positive integer required: perspective." + name)
    for section in ("lineage","perspective"):
        for name in ("optimizer_seconds","native_timeout_seconds"):
            value=config[section][name]
            if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<=0:
                raise SetupError("Finite positive runtime allowance required: "+section+"."+name)
    terminal=config["perspective"]["conditional"]
    for name in ("permanent_anchors","finalists","finalist_best_count"):
        if type(terminal[name]) is not int or terminal[name]<1:raise SetupError("Positive terminal quota required: "+name)
    if terminal["finalist_best_count"]>terminal["finalists"]:raise SetupError("Best finalist quota exceeds total quota")
    if terminal["minority_probe_fractions"]!=[.01,.05,.95,.99]:
        raise SetupError("Probe sensitivity operators require the confirmed 1/5/95/99percent probes")
    for stage in ("screen","final_validation"):
        duration=terminal["native_stage_deadline_seconds"][stage]
        if duration is not None and (not math.isfinite(duration) or duration<=0):raise SetupError("Relative stage deadlines must be positive seconds or null")
    if config["lineage"]["groups"] != ["2N", "4N"] or config["perspective"]["groups"] != ["2N", "4N"]:
        raise SetupError("This frozen SUM-159 pilot adapter requires explicit 2N/4N groups; another study needs its own prepared-data adapter")
    if config["inputs"]["permit_legacy_image_access"]:
        raise SetupError("Legacy imaging access is prohibited in this setup")
    if config["inputs"]["mode"] != "frozen_prepared_measurements":
        raise SetupError("Raw data preparation adapter is not implemented; select frozen_prepared_measurements or complete the documented preparation interface")
    if not inside(resolve(config, "output_root"), resolve(config,"scratch_root")):
        raise SetupError("output_root must remain inside the configured scratch_root")
    if inside(resolve(config,"scratch_root"),PACKAGE):raise SetupError("Runtime scratch_root must stay outside the public source package")
    for key in ("prepared_data", "lineage_engine", "perspective_engine"):
        if resolve(config,key) is not None and "hypothesis_tests" in resolve(config, key).parts:
            raise SetupError("Runtime paths cannot point into historical pilot runs: " + key)
    observation = config["observation"]
    if observation["shape_columns"] != 30 or observation["weight_columns"] != 6:
        raise SetupError("This adapter requires the pilot's 30-column/six-component observer")
    if observation["coefficients"] != [.5, .1, .1, .1, .1, .1]:
        raise SetupError("Observation coefficients differ from the current agreed pilot contract")
    if observation["field_shape"] != [1100,1400] or abs(observation["count_offset"]-math.log(1540000))>1e-12:
        raise SetupError("Changed geometry/count conversion requires an explicitly revised observer adapter")
    lineage_contract=read(PACKAGE/"contracts.json")["lineage"]
    perspective_contract=read(PACKAGE/"contracts.json")["perspective"]
    if config["lineage"]["natural_bounds"]!=lineage_contract["natural_bounds"] or config["lineage"]["parameter_names"]!=lineage_contract["parameter_names"]:
        raise SetupError("Lineage parameter names/bounds differ from the frozen scientific adapter")
    if config["perspective"]["bounds"]!=perspective_contract["bounds"] or config["perspective"]["parameter_names"]!=perspective_contract["parameter_names"]:
        raise SetupError("Perspective parameter names/bounds differ from the frozen scientific adapter")
    if config["perspective"]["no_transitions"] is not True or config["perspective"]["assay_loss_coefficient"]!=1.0 or config["perspective"]["state_ridge_denominator"]!="log(1.5)":
        raise SetupError("Changed perspective mechanisms/loss require a revised scientific adapter")
    if config["perspective"]["state_parameter_indices_from_lineage"]!=[0,1,2,3,6,7,8,9,10,11,12,13,14] or config["perspective"]["common_initialization_indices_from_lineage"]!=[4,5]:
        raise SetupError("Ambiguous shared-to-perspective parameter mapping")
    for section, key in (("lineage", "alphas"), ("perspective", "alphas")):
        values = config[section][key]
        if not values or len(values) != len(set(values)) or any(v < 0 or not math.isfinite(v) for v in values):
            raise SetupError("Unique finite nonnegative alphas required: " + section)
    return config


def validate_graph(episodes, observations):
    byid = {p["episode_id"]: p for p in episodes}
    if len(byid) != len(episodes):
        raise SetupError("Duplicate episode ID")
    order = {p["episode_id"]: i for i, p in enumerate(episodes)}
    depths, support = {}, []
    for p in episodes:
        eid, parent = p["episode_id"], p["parent_episode_id"]
        if parent is not None:
            if parent not in byid or order[parent] >= order[eid]:
                raise SetupError("Episodes must be topologically ordered with every parent present: " + eid)
            if byid[parent]["founding_group"] != p["founding_group"]:
                raise SetupError("Cross-founder ancestry: " + eid)
            outgoing = [c for c in byid[parent]["children"] if c["child_episode_id"] == eid]
            if len(outgoing) != 1 or abs(outgoing[0]["time_days"] - p["parent_transfer_time_days"]) > 1e-9:
                raise SetupError("Transfer timing mismatch: " + eid)
        depths[eid] = 0 if parent is None else depths[parent] + 1
        indices = p["observation_rows"]
        if len(indices) != len(p["observation_times_days"]):
            raise SetupError("Observation-time support mismatch: " + eid)
        for i, t in zip(indices, p["observation_times_days"]):
            if observations[i]["episode_id"] != eid or abs(float(observations[i]["time_days"]) - t) > 1e-8:
                raise SetupError("Row/time/episode join mismatch: " + eid)
        support.extend(indices)
    if sorted(support) != list(range(len(observations))):
        raise SetupError("Each observed row must join exactly once to an episode")
    return depths


def validate_cellsegmentations(config):
    """Only an explicit CellSegmentations-relative raw/mask/feature join is usable."""
    raw_root = os.environ.get("CELLSEGMENTATIONS_ROOT") or config["paths"]["cellsegmentations_root"]
    manifest_path = resolve(config, "cellsegmentations_manifest")
    if not raw_root or manifest_path is None:
        return {"status": "not_available", "reason": "No supported raw/mask/features manifest configured; prepared measurements only", "files_opened": 0}
    root = Path(raw_root).expanduser().resolve()
    if "CellSegmentations" not in root.parts or not root.is_dir():
        raise SetupError("Imaging root must resolve to CellSegmentations or a directory below it")
    rows = list(csv.DictReader(manifest_path.open()))
    if not rows:
        raise SetupError("Empty imaging manifest")
    keys = ["field_id", "raw_relative_path", "mask_relative_path", "features_relative_path", "raw_sha256", "mask_sha256", "features_sha256"]
    seen = set()
    for row in rows:
        if any(not row.get(key) for key in keys):
            raise SetupError("Manifest requires field ID and relative path + SHA256 for raw, mask and features")
        if row["field_id"] in seen:
            raise SetupError("Duplicate imaging field ID")
        seen.add(row["field_id"])
        for product in ("raw", "mask", "features"):
            rel = Path(row[product + "_relative_path"])
            path = (root / rel).resolve()
            if rel.is_absolute() or not inside(path, root) or not path.is_file():
                raise SetupError("Invalid CellSegmentations product path: " + str(rel))
            if sha(path) != row[product + "_sha256"]:
                raise SetupError("CellSegmentations product hash mismatch: " + str(rel))
    return {"status": "verified_file_join", "fields": len(rows), "root": str(root), "manifest_sha256": sha(manifest_path), "files_opened": 3 * len(rows), "pixel_label_feature_alignment": "Not checked by file join; required before raw reconstruction"}


def preflight(config, config_path):
    errors, blockers, warnings = [], [], []
    frozen_manifest=PACKAGE/"source_manifest.json"
    if frozen_manifest.exists():
        try:verify_package()
        except (SetupError,FileNotFoundError) as error:errors.append(str(error))
    else:
        errors.append("Missing public source_manifest.json")
    data_root = resolve(config, "prepared_data")
    for name in config["inputs"]["required"]:
        path = data_root / name if data_root is not None else None
        expected = config["inputs"]["prepared_hashes"].get(name)
        if path is None:
            errors.append("Set paths.prepared_data or BASELINES_PREPARED_DATA (missing "+name+")")
        elif not path.is_file():
            errors.append("Missing prepared input: " + str(path))
        elif expected is None or sha(path) != expected:
            errors.append("Prepared input missing/mismatching expected identity: " + name)
    dependencies = {name: importlib.util.find_spec(name) is not None for name in ("numpy", "scipy", "pandas", "numba", "skimage", "matplotlib")}
    for name, exists in dependencies.items():
        if not exists:
            errors.append("Missing dependency in preflight interpreter: " + name)
    if not resolve(config, "python").is_file():
        errors.append("Configured compute Python is missing")
    for name in ("lineage_engine", "perspective_engine"):
        path = resolve(config, name)
        if path is None or not path.is_file() or not os.access(path, os.X_OK):
            errors.append("Missing executable: " + name)
    runtime_scan = []
    for path in sorted((PACKAGE / "vendor").rglob("*.py")):
        text = path.read_text()
        try:
            ast.parse(text)
        except SyntaxError as e:
            errors.append("Invalid copied source: " + str(e))
        for token in ("hypothesis_tests/", "20261016_180145_sum159", "20261016_190611_sum159", "legacy_image_root"):
            if token in text:
                runtime_scan.append({"file": str(path.relative_to(PACKAGE)), "forbidden_runtime_reference": token})
    if runtime_scan:
        errors.append("Historical path remains in runtime source")
    prepared = {}
    if not errors:
        import numpy as np
        rows = list(csv.DictReader((data_root / "observations.csv").open()))
        episodes, assays = read(data_root / "episodes.json"), read(data_root / "assays.json")
        with np.load(data_root / "observations.npz", allow_pickle=False) as arrays:
            observed, scales, weights = [arrays[k] for k in ("observed", "scales", "weights")]
            if observed.shape != (len(rows), 30) or scales.shape != observed.shape or weights.shape != (len(rows), 6):
                errors.append("Prepared arrays do not match declared observation schema")
            elif not (np.isfinite(observed).all() and np.isfinite(scales).all() and np.isfinite(weights).all() and (scales > 0).all() and (weights >= 0).all()):
                errors.append("Prepared observations/scales/weights invalid")
            elif not (np.allclose(weights.sum(axis=0), 1) and (observed[:, 0] >= observed[:, 1]).all()):
                errors.append("Weights/count partition invalid")
            for group in config["lineage"]["groups"]:
                ids = [i for i, row in enumerate(rows) if row["group"] == group]
                if not np.allclose(weights[ids].sum(axis=0), .5):
                    errors.append("Founder balance invalid: " + group)
        depths = validate_graph(episodes, rows)
        byid = {p["episode_id"]: p for p in episodes}
        assay_ids = set()
        for assay in assays:
            if assay["id"] in assay_ids or assay["episode_id"] not in byid or not 0 <= assay["k"] <= assay["n"] or assay["n"] <= 0:
                errors.append("Invalid or duplicate assay")
            assay_ids.add(assay["id"])
        fields = list(csv.DictReader((data_root / "field_measurements.csv").open()))
        for field in fields:
            if int(field["n_cells"]) != int(field["live_count"]) + int(field["dead_count"]):
                errors.append("Field total != live + dead")
                break
        for i, row in enumerate(rows):
            joined = [f for f in fields if int(f["row"]) == i]
            if not joined or abs(math.log1p(sum(int(f["n_cells"]) for f in joined) / len(joined)) - observed[i, 0]) > 1e-9:
                errors.append("Frozen field count/observation join mismatch: " + str(i))
                break
        prepared = {"rows": len(rows), "episodes": len(episodes), "fields": len(fields), "assays": len(assays), "assay_cells": sum(a["n"] for a in assays), "oxygen_values": sorted({float(row["oxygen"]) for row in rows}), "even_depth_episodes": sum(v % 2 == 0 for v in depths.values()), "historical_image_paths_dereferenced": 0}
    import storage_budget
    storage=storage_budget.storage_plan(config,prepared)
    errors.extend(storage['errors']);storage_inventory=None
    roots=config['storage'].get('project_scope_roots',[])
    if roots:
        def scoped(value):
            path=Path(value).expanduser();return path.resolve() if path.is_absolute() else (Path(config['_config_dir'])/path).resolve()
        try:
            inventory_file=config['storage'].get('inventory_file')
            owned=[scoped(p) for p in roots];readonly=[scoped(p) for p in config['storage'].get('read_only_external_roots',[])]
            storage_inventory=storage_budget.frozen_inventory(scoped(inventory_file),config['storage'].get('inventory_sha256'),owned,readonly,config['storage'].get('inventory_max_age_seconds',600)) if inventory_file else storage_budget.inventory(owned,readonly)
            storage_inventory['verified']=True
            if storage_inventory['bytes']+config['storage']['new_durable_bytes_reservation']>config['storage']['durable_limit_bytes']:errors.append('Actual project inventory plus reserved durable growth exceeds50GB')
        except (OSError,ValueError) as error:errors.append('Project storage inventory: '+str(error))
    else:blockers.append('Explicit project-owned home/shared/scratch roots and a fresh complete inventory are required before launch')
    imaging = validate_cellsegmentations(config)
    if imaging["status"] == "not_available":
        warnings.append(imaging["reason"])
    if not config["execution"]["authorized"]:
        blockers.append("New execution is not authorized; setup-only instruction remains active")
    if config["resources"]["budget_cpu_hours_cap"] is None:
        warnings.append("CPU-hour envelope remains provisional; review configured resource limits before any later launch")
    if not config["execution"]["perspective_source_accepted"]:
        blockers.append("Scientific source acceptance must be recorded before execution")
    if config["execution"]["terminal_policy"] != "conditional_native_correction_refinement_independent_finalists":
        errors.append("Terminal policy differs from the confirmed executed190611 procedure")
    if not config["resources"].get("scheduler_limits_verified",False):
        blockers.append("Compute-node environment, scheduler array/job limits and native transfer require execution-time checks; no probes or simulations were performed here")
    warnings.append("Configured compute interpreter dependencies and ELF shared libraries need compute-node verification; this inspection checks the active lightweight interpreter only")
    warnings.append("Microscopy and assay data share experimental ancestry; scores are composite summaries, not model evidence or Bayes factors")
    return {"schema_version": VERSION, "time_utc": utc(), "setup_valid": not errors, "execution_ready": not errors and not blockers, "errors": errors, "execution_blockers": blockers, "warnings": warnings, "dependencies_active_interpreter": dependencies, "active_interpreter": sys.executable, "configured_compute_interpreter": str(resolve(config, "python")), "prepared_data": prepared, "storage_plan":storage,"storage_inventory":storage_inventory,"imaging": imaging, "runtime_source_scan": runtime_scan, "config_sha256": sha(config_path), "scientific_modules_imported": [name for name in sys.modules if name.startswith(("lineage_model", "perspective_model", "perspective_search", "wgd_colony", "wgd_transfer", "core."))], "jobs_submitted": 0, "fits_or_simulations_run": 0}


def command(config_path, phase, *extra):
    return [str(resolve(load_config(config_path), "python")), str(PACKAGE / "workflow.py"), "worker", "--config", str(Path(config_path).resolve()), "--run", "<NEW_RUN>", "--phase", phase, *extra]


def dependency_plan(config, config_path, check):
    import scheduler
    observed=check.get("prepared_data",{})
    if not observed:
        return {"mode":"SETUP_ONLY_DRY_RUN","setup_valid":False,"errors":check["errors"],"nodes":[],"no_scheduler_calls":True}
    proposed_run=resolve(config,"output_root")/"PLANNED_NEW_RUN_ONLY"
    spec=scheduler.campaign_spec(config,config_path,proposed_run,observed)
    scheduler_plan=scheduler.plan(spec,resolve(config,"scratch_root")/"planning/scheduler",materialize=False)
    l=config["lineage"];p=config["perspective"];c=p["conditional"]
    oxygen=len(observed["oxygen_values"]);ridge_count=l["ridge_starts_per_alpha"]*len(l["alphas"])
    shared_native=l["native_pool"]["shared"]*oxygen*l["replicates"]
    ridge_native=l["native_pool"]["ridge_per_alpha"]*len(l["alphas"])*oxygen*len(l["groups"])*l["replicates"]
    selected=c["screen_candidates_per_alpha"]*len(p["alphas"])
    screen_native=selected*c["screen_replicates"]*(c["screen_passages"]+oxygen*len(c["minority_probe_fractions"]))
    final_native=c["finalists"]*c["final_replicates"]*(observed["episodes"]+oxygen*len(c["minority_probe_fractions"]))
    return {"mode":"SETUP_ONLY_DRY_RUN","execution_ready":check["execution_ready"],"execution_blockers":check["execution_blockers"],"nodes":spec["nodes"],"scheduler_specification":spec,"common_totals":{"planned_tasks":scheduler_plan["total_array_tasks"],"lineage_new_fits":l["shared_starts"]+ridge_count,"lineage_native_trajectories":shared_native+ridge_native,"perspective_new_search_fits":p["starts_per_alpha"]*len(p["alphas"]),"perspective_bounded_refinement_slots":selected*c.get("refinement_replicates",1),"perspective_refinement_replicates":c.get("refinement_replicates",1),"perspective_screen_native_trajectories":screen_native,"perspective_final_native_trajectories":final_native,"perspective_all_native_trajectories":screen_native+final_native,"oxygen_levels":oxygen,"native_replicates_are_configurable":True},"terminal_policy":{"selected":"conditional_native_correction_refinement_independent_finalists","selection":"executed top5+5 screen rule, two anchors; two best distinct-source finalists plus competitive diverse third","screen_passages":c["screen_passages"],"screen_replicates":c["screen_replicates"],"final_passages":observed["episodes"],"final_replicates":c["final_replicates"],"acceptance":config["execution"]["acceptance_policy"],"post_validation_adaptive_nodes":[],"implementation_complete":True},"storage_plan":check.get("storage_plan"),"resource_plan":{"status":config["resources"]["status"],"fit_optimizer_allowance_cpu_hours":((l["shared_starts"]+ridge_count)*l["optimizer_seconds"]+p["starts_per_alpha"]*len(p["alphas"])*p["optimizer_seconds"]+selected*c.get("refinement_replicates",1)*c["refinement_seconds"])/3600,"fit_allowance_excludes":"JIT/start screening, finalization, analysis, failed attempts and reports; measure separately","lineage_native_timeout_ceiling_cpu_hours":(shared_native+ridge_native)*l["native_timeout_seconds"]/3600,"perspective_native_timeout_ceiling_cpu_hours":(screen_native+final_native)*p["native_timeout_seconds"]/3600,"relative_stage_deadlines":c["native_stage_deadline_seconds"],"deadline_origin":c["deadline_origin"],"historical_lineage_measured_cpu_hours":34.0167,"historical_lineage_allocated_cpu_hours":70.1492,"historical_usage_is_context_only":True,"elapsed_estimate":None,"queue_and_dependency_time":"Separate Eligible/Start timing where available; not CPU use"},"runtime_provenance":{"parameter_reuse":"none from historical runs","new_parent_source":"NEW_RUN/lineage/shared_scores.json, matching run/input identities and complete native support","measurement_reuse":config["inputs"]["scratch_boundary"],"config_sha256":sha(config_path)},"no_scheduler_calls":True,"no_scientific_imports":True}


def stratified(bounds, count, seed):
    import numpy as np
    bounds = np.asarray(bounds, float)
    rng = np.random.default_rng(seed)
    q = np.column_stack([(rng.permutation(count)+rng.random(count))/count for _ in bounds])
    return bounds[:, 0] + q*np.diff(bounds, axis=1).ravel()


def freeze_package():
    """Public source is immutable at runtime; validate its maintained hash manifest."""
    return verify_package()


def verify_package():
    manifest = read(PACKAGE/"source_manifest.json")
    for entry in manifest["files"]:
        if sha(PACKAGE/entry["path"]) != entry["sha256"]:
            raise SetupError("Frozen package changed: " + entry["path"])
    for entry in manifest.get("repository_files",[]):
        if sha(PACKAGE.parents[4]/entry["path"])!=entry["sha256"]:raise SetupError("Public interface changed: "+entry["path"])
    return sha(PACKAGE/"source_manifest.json")


def prepare(config, config_path, run_name):
    check = preflight(config, config_path)
    if not check["setup_valid"]:
        raise SetupError("Input/source/dependency preflight failed: " + "; ".join(check["errors"]))
    if not run_name or Path(run_name).name != run_name or run_name in {".", ".."}:
        raise SetupError("Run name must be a single new directory name")
    output = resolve(config, "output_root") / run_name
    if output.exists():
        raise SetupError("Run directory exists; never overwrite/resume automatically: " + str(output))
    package_hash = verify_package()
    output.mkdir(parents=True, exist_ok=False)
    config_value_hash=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    run = {"run_id": run_name, "created_utc": utc(), "package_manifest_sha256": package_hash, "config_sha256": sha(config_path), "config_value_sha256":config_value_hash, "scratch_parameter_boundary": True, "prepared_only": True, "scientific_work_started": False}
    write(output/"run_identity.json", run)
    write(output/"config.json", config)
    input_hashes = {}
    for name in config["inputs"]["required"]:
        source = resolve(config, "prepared_data")/name
        target = output/"inputs"/name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
        input_hashes[name] = sha(target)
    write(output/"input_manifest.json", {"run_id": run_name, "files": input_hashes, "prepared_data_reuse_only": True})
    write(output/"runtime_dependencies.json",{"files":[{"role":key,"path":str(resolve(config,key)),"sha256":sha(resolve(config,key))} for key in ["python","lineage_engine","perspective_engine"]],"python_version_preparation_interpreter":sys.version})
    for stage in ("lineage", "perspective"):
        (output/stage).mkdir()
        # Both phases consume one frozen numerical support, without copying fit outputs.
        (output/stage/"inputs").symlink_to("../inputs", target_is_directory=True)
    import numpy as np
    l = config["lineage"]
    bounds = np.log(np.asarray(l["natural_bounds"]))
    starts = stratified(bounds, l["shared_starts"], l["seed_shared_starts"])
    if l["first_start_policy"] == "illustrative_parameters_with_prepared_early_count_density":
        rows = list(csv.DictReader((output/"inputs/observations.csv").open()))
        with np.load(output/"inputs/observations.npz") as a:
            indices = [i for i,row in enumerate(rows) if float(row["time_days"]) <= .1]
            rho = float(np.median(np.expm1(a["observed"][indices,0]))/(1100*1400)) if indices else 1e-4
        starts[0] = np.log([.85,1000,1,15,float(np.clip(rho,1e-6,.005)),5,1,.65,2,1,1,4,.076560048,8.6,.03])
    elif l["first_start_policy"] != "all_stratified":
        raise SetupError("Unknown first-start policy")
    candidates = [{"id": f"shared_{i:04}", "stage": "shared", "alpha": 0., "seed": l["seed_shared_candidates"]+i, "initial": x.tolist(), "origin": "fresh deterministic design; no historical fitted vectors", "run_id": run_name} for i,x in enumerate(starts)]
    write(output/"lineage/shared_candidates.json", candidates)
    write(output/"plan.json", dependency_plan(config, config_path, check))
    write(output/"preflight.json", check)
    import storage_budget
    inventory=check.get("storage_inventory") or {"bytes":config["storage"]["existing_project_bytes_estimate"],"verified":False,"scope":"dry preparation estimate only; not launch-ready"}
    storage_budget.initialize(output,config,inventory)
    return output


def run_check(run, config_path=None):
    run = Path(run).resolve()
    identity = read(run/"run_identity.json")
    config = read(run/"config.json")
    if hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()!=identity["config_value_sha256"]:
        raise SetupError("Frozen run configuration changed")
    if not inside(run, resolve(config, "output_root")):
        raise SetupError("Run outside isolated output root")
    if identity["package_manifest_sha256"] != verify_package():
        raise SetupError("Run package identity changed")
    if config_path is not None and sha(config_path) != identity["config_sha256"]:
        raise SetupError("Run configuration differs from supplied configuration")
    manifest = read(run/"input_manifest.json")
    for name, expected in manifest["files"].items():
        if sha(run/"inputs"/name) != expected:
            raise SetupError("Frozen run input changed: " + name)
    return run, config, identity


def verify_runtime_dependencies(run):
    for item in read(Path(run)/"runtime_dependencies.json")["files"]:
        if sha(item["path"])!=item["sha256"]:raise SetupError("Frozen runtime dependency changed: "+item["role"])


def fresh_shared_parent(run):
    """A declared last-resort *unfitted* current-run design point, never an old fit."""
    candidate=read(Path(run)/"lineage/shared_candidates.json")[0]
    return {"status":"unfitted_initial","candidate":dict(candidate,id="fresh_initial_"+candidate["id"]),"source_candidate":candidate,"x":candidate["initial"],"ranking_score":None,"ranking_basis":"fresh_unfitted_initial","approximation_data_loss":None,"parent_source":"current_run_fresh_design"}


def parent_ranking_key(value):
    evidence=value.get("ranking_evidence",{})
    basis=value.get("ranking_basis")
    tier=0 if basis=="native_full" else 1 if basis=="native_partial_normalized" else 2
    pattern=evidence.get("pattern_sha256") or hashlib.sha256(json.dumps(value.get("native_support",[]),sort_keys=True,allow_nan=False).encode()).hexdigest()
    return (tier,-evidence.get("component_fraction",0.),-evidence.get("weight_fraction",0.),pattern if tier==1 else "",value["ranking_score"] if value["ranking_score"] is not None else math.inf,value["candidate"]["id"])


def current_shared_parents(run, config):
    """Prefer full native evidence, then partial native evidence, then saved valid fits.

    Missing native evidence is a degradation. Foreign or altered evidence is an error.
    The last resort remains a fresh current-run design point and must pass embedding.
    """
    run, _, identity = run_check(run)
    scores_path=run/"lineage/shared_scores.json";provenance=run/"lineage/shared_score_provenance.json"
    starts={c["id"]:c for c in read(run/"lineage/shared_candidates.json")}
    bounds=config["lineage"]["natural_bounds"]
    def vector_ok(x):
        return len(x)==15 and all(math.isfinite(v) and math.log(bounds[i][0])-1e-12<=v<=math.log(bounds[i][1])+1e-12 for i,v in enumerate(x))
    parents=[]
    if scores_path.exists() and provenance.exists():
        proof=read(provenance)
        if proof.get("run_id")!=identity["run_id"] or proof.get("scores_sha256")!=sha(scores_path) or proof.get("input_manifest_sha256")!=sha(run/"input_manifest.json"):
            raise SetupError("Shared ranking does not belong to this frozen new run")
        for value in read(scores_path):
            if value.get("status") not in {"complete","partial"}:continue
            candidate=value["candidate"];cid=candidate["id"]
            if cid not in starts or starts[cid]["run_id"]!=identity["run_id"] or candidate!=starts[cid]:raise SetupError("Shared score references a foreign candidate")
            score=value.get("simulator_data_loss") if value["status"]=="complete" else value.get("partial_simulator_data_loss")
            if not vector_ok(value.get("x",[])) or not isinstance(score,(int,float)) or not math.isfinite(score):raise SetupError("Invalid shared parent vector/ranking loss")
            parents.append(dict(value,ranking_score=score,ranking_basis="native_full" if value["status"]=="complete" else "native_partial_normalized",parent_source="current_run_shared_score"))
    # Keep score types separate: complete support takes precedence over partial support.
    full=[p for p in parents if p["ranking_basis"]=="native_full"]
    if full:parents=full
    if not parents:
        for cid,candidate in starts.items():
            folder=run/"lineage/candidates"/cid;path=folder/"final.json";proof_path=folder/"final_provenance.json"
            if not path.exists() or not proof_path.exists():continue
            proof=read(proof_path)
            if proof.get("run_id")!=identity["run_id"] or proof.get("final_sha256")!=sha(path) or proof.get("input_manifest_sha256")!=sha(run/"input_manifest.json"):
                raise SetupError("Shared finalization is foreign/modified")
            final=read(path);score=final.get("data_loss")
            if final.get("invalid") or not vector_ok(final.get("x",[])) or not isinstance(score,(int,float)) or not math.isfinite(score):continue
            parents.append({"status":"approximation_fallback","candidate":candidate,"x":final["x"],"ranking_score":score,"ranking_basis":"approximation_fallback","approximation_data_loss":score,"assumption_penalty":final.get("assumption_penalty"),"parent_source":"current_run_valid_final"})
    parents.sort(key=parent_ranking_key)
    if not parents:parents=[fresh_shared_parent(run)]
    return parents


def prepare_ridge(run):
    import numpy as np
    run, config, identity = run_check(run)
    destination=run/"lineage/ridge_candidates.json"
    if destination.exists():
        raise SetupError("Ridge candidates already frozen; no overwrite")
    l=config["lineage"];parents=current_shared_parents(run,config);best=parents[0]
    bounds=np.log(l["natural_bounds"]);span=np.diff(bounds,axis=1).ravel()
    competitive=[p for p in parents[1:] if best["ranking_basis"]!="native_full" or p["ranking_score"] is not None and best["ranking_score"] is not None and p["ranking_score"]<=best["ranking_score"]*(1+l["parent_competitive_window"])]
    if not competitive:competitive=parents[1:]
    # Accepted lineage pilot's maximin diverse-parent rule, deterministic ID ties.
    others=[];chosen=[best]
    while competitive and len(others)<max(1,l["ridge_starts_per_alpha"]//2):
        p=min(competitive,key=lambda p:(-min(float(np.linalg.norm((np.asarray(p["x"])-np.asarray(q["x"]))/span)) for q in chosen),p["ranking_score"],p["candidate"]["id"]))
        competitive.remove(p);others.append(p);chosen.append(p)
    rng=np.random.default_rng(l["seed_ridge"]);candidates=[]
    for ai,alpha in enumerate(l["alphas"]):
        half=l["ridge_starts_per_alpha"]//2
        for i in range(l["ridge_starts_per_alpha"]):
            p=best if i<half or not others else others[(i-half)%len(others)]
            x=np.tile(p["x"],2)
            if i:
                x=np.clip(x+rng.normal(size=30)*np.tile(span,2)*(.025 if i%max(1,half)<3 else .08),np.tile(bounds[:,0],2),np.tile(bounds[:,1],2))
            candidates.append({"id":f"ridge_a{ai:02}_{i:04}","stage":"ridge","alpha":alpha,"initial":x.tolist(),"seed":l["seed_ridge"]+len(candidates),"parent":p["candidate"]["id"],"parent_scores_sha256":sha(run/"lineage/shared_scores.json") if (run/"lineage/shared_scores.json").exists() else None,"parent_run_id":identity["run_id"],"origin":"current-run shared parent; "+p["ranking_basis"],"parent_ranking_basis":p["ranking_basis"],"parent_fallback":not bool(others) and i>=half})
    write(destination,candidates)
    return candidates


def prepare_perspective(run, eligible_shared_ids=None, finalize_screened_pool=False, embedding_results=None):
    """Mirror current explore.prepare mapping without evaluating any model."""
    import numpy as np
    run, config, identity=run_check(run);p=config["perspective"]
    if (run/"perspective/candidates.json").exists() and not finalize_screened_pool:
        raise SetupError("Perspective starts already frozen; no overwrite")
    ranked=current_shared_parents(run,config)
    best=ranked[0]["ranking_score"]
    parents=[q for q in ranked if ranked[0]["ranking_basis"]!="native_full" or best is None or q["ranking_score"] is not None and q["ranking_score"]<=best*(1+p["shared_parent_competitive_window"])]
    # The competitive window is a preference, not a prerequisite for useful work.
    target=p["conditional"]["permanent_anchors"]
    for parent in ranked:
        if len(parents)>=target:break
        if parent not in parents:parents.append(parent)
    fresh=fresh_shared_parent(run)
    fresh_fallback=[] if any(q["candidate"]["id"]==fresh["candidate"]["id"] for q in parents) else [fresh]
    if eligible_shared_ids is not None:
        eligible=set(eligible_shared_ids)
        parents=[q for q in parents if q["candidate"]["id"] in eligible]
        if not parents:parents=[q for q in fresh_fallback if q["candidate"]["id"] in eligible]
        fresh_fallback=[]
    if finalize_screened_pool:
        if (run/"perspective/embedding_check.json").exists():raise SetupError("Perspective numerical parent screen already finalized")
        if (run/"perspective/candidates").exists() and any((run/"perspective/candidates").iterdir()):raise SetupError("Cannot change perspective starts after scientific candidate outputs exist")
        for name in ("parents.json","anchors.json","candidates.json"):
            path=run/"perspective"/name
            if path.exists():
                archived=path.with_name("initial_proposals_"+name)
                if archived.exists():raise SetupError("Perspective proposal archive already exists")
                path.rename(archived)
    assays=read(run/"inputs/assays.json")
    founder=[]
    for group in p["groups"]:
        qs=[q for q in assays if q["group"]==group]
        if not qs or sum(q["n"] for q in qs)==0:
            raise SetupError("Missing founder assay initialization support")
        founder.append(float(np.clip(sum(q["k"] for q in qs)/sum(q["n"] for q in qs),1e-6,1-1e-6)))
    def mapped_parent(parent):
        parent=dict(parent)
        evaluated=(embedding_results or {}).get(parent["candidate"]["id"])
        if evaluated:
            parent.update(approximation_data_loss=evaluated["data_loss"],assumption_penalty=evaluated.get("assumption_penalty",0.))
        z=np.asarray(parent["x"]);biology=z[p["state_parameter_indices_from_lineage"]]
        x=np.r_[founder,np.log(1e-12),0.,1.,z[p["common_initialization_indices_from_lineage"]],biology,biology]
        return {"id":parent["candidate"]["id"],"x":x.tolist(),"native_microscopy_loss":parent.get("simulator_data_loss"),"ranking_score":parent["ranking_score"],"ranking_basis":parent["ranking_basis"],"reference":parent,"embedding_result":evaluated,"run_id":identity["run_id"]}
    mapped=[mapped_parent(parent) for parent in parents]
    mapped_fresh=[mapped_parent(parent) for parent in fresh_fallback]
    bounds=np.asarray(p["bounds"]);width=np.diff(bounds,axis=1).ravel();candidates=[]
    def founder_draw(rng):
        u=rng.random()
        low=10**rng.uniform(-9,np.log10(.5)) if u<.6 else rng.uniform(.01,.99) if u<.85 else 1-10**rng.uniform(-8,-.31)
        high=1-10**rng.uniform(-9,np.log10(.5)) if rng.random()<.75 else rng.uniform(.01,.99)
        return [low,high]
    for ai,alpha in enumerate(p["alphas"]) if mapped else []:
        half=p["starts_per_alpha"]//2
        for i in range(p["starts_per_alpha"]):
            ix=ai*p["starts_per_alpha"]+i;rng=np.random.default_rng(p["seed_search"]+1000+ix)
            parent=mapped[0] if i<half or len(mapped)==1 else mapped[1+(i-half)%(len(mapped)-1)]
            fallback=np.asarray(parent["x"]);x=fallback.copy();kind="unchanged_shared_anchor"
            if i:
                kind=["small_contrasts","moderate_contrasts","broad_contrasts","selection_focused"][i%4]
                x[5:]+=rng.normal(0,[.005,.02,.055,.012][i%4],28)*width[5:]
                x[:2]=founder_draw(rng)
                if i%4==3:
                    for lo,hi in [(13,26),(14,27),(15,28),(16,29),(17,30),(18,31),(19,32)]:
                        x[[lo,hi]]+=rng.normal(0,.10,2)*width[[lo,hi]]
                x[3:5]=[0.,1.] if ix%5==0 else [rng.beta(1.2,3),rng.uniform(0,1)]
            x[2]=np.log(1e-12);x=np.clip(x,bounds[:,0],bounds[:,1]);x[:2]=np.clip(x[:2],1e-10,1-1e-10)
            candidates.append({"id":f"no_wgd_a{ai:02}_{i:04}","index":ix,"family":"no_wgd","alpha":alpha,"seed":p["seed_search"]+1000+ix,"initial":x.tolist(),"parent":parent["id"],"parent_x":parent["x"],"fallback_initial":fallback.tolist(),"origin":kind,"parent_ranking_basis":parent["ranking_basis"],"search_seconds":p["optimizer_seconds"],"parent_run_id":identity["run_id"],"parent_scores_sha256":sha(run/"lineage/shared_scores.json") if (run/"lineage/shared_scores.json").exists() else None})
    write(run/"perspective/parents.json",{"shared":mapped,"fresh_fallback":mapped_fresh,"incumbents":[],"initialization":"same-run shared evidence; full native preferred, partial/approximation/fresh design explicitly labeled","degraded":len(mapped)<target or any(parent["ranking_basis"]!="native_full" for parent in mapped),"status":"available" if mapped else "unavailable_invalid_parent_embeddings","parent_run_id":identity["run_id"],"parent_scores_sha256":sha(run/"lineage/shared_scores.json") if (run/"lineage/shared_scores.json").exists() else None,"numerical_embedding_check":"pending execution; no scientific model evaluated during setup"})
    write(run/"perspective/anchors.json",[{"id":"anchor_"+parent["id"],"family":"no_wgd","alpha":0.,"initial":parent["x"],"x":parent["x"],"parent":parent["id"],"origin":"identical-state shared physical anchor; fresh two-state native evaluation still required"} for parent in mapped])
    write(run/"perspective/candidates.json",candidates)
    return candidates


def execution_gate(config):
    """No default or dry-run command can reach scientific imports."""
    for key in ("authorized",):
        if config["execution"].get(key) is not True:
            raise SetupError("Scientific worker disabled: execution."+key+" is false")
    if config["execution"]["terminal_policy"] is None:
        raise SetupError("Scientific worker disabled: missing terminal policy")
    if not os.environ.get("SLURM_JOB_ID"):
        raise SetupError("Scientific workers require SLURM")


def embedding_parents(run):
    value=read(Path(run)/"perspective/parents.json")
    return value["shared"]+value.get("fresh_fallback",[])


def finalize_embeddings(run):
    """Reduce independently evaluated parent checks, retaining useful valid parents."""
    run,config,_=run_check(run);root=run/"perspective";parents=read(root/"parents.json")
    checks=[];valid=[];evaluated={}
    for index,parent in enumerate(embedding_parents(run)):
        path=root/"embedding_checks"/(str(index)+".json")
        value=read(path) if path.exists() else {"parent":parent["id"],"valid":False,"status":"missing_parent_check"}
        if path.exists() and (value.get("parent_sha256")!=hashlib.sha256(json.dumps(parent,sort_keys=True,allow_nan=False).encode()).hexdigest()):raise SetupError("Parent embedding check references modified parameters")
        checks.append(value)
        if value.get("valid"):
            valid.append(parent["id"])
            evaluated[parent["id"]]=value["evaluation"]
    primary=[p["id"] for p in parents["shared"] if p["id"] in valid]
    eligible=primary or [p["id"] for p in parents.get("fresh_fallback",[]) if p["id"] in valid]
    prepare_perspective(run,eligible_shared_ids=eligible,finalize_screened_pool=True,embedding_results=evaluated)
    candidates=read(root/"candidates.json")
    write(root/"embedding_check.json",{"checks":checks,"passed":bool(candidates),"status":"available" if candidates else "unavailable_no_valid_model_initialization","eligible_parent_ids":eligible,"fresh_initialization_fallback":bool(eligible and not primary),"degraded":len(eligible)<config["perspective"]["conditional"]["permanent_anchors"] or not primary,"parents_sha256":sha(root/"parents.json"),"candidates_sha256":sha(root/"candidates.json"),"assay_objective_is_additional":True,"same_stochastic_native_realization_claimed":False,"finite_embedding_differences_are_diagnostic":True})
    import scheduler
    scheduler.trim_unused(run,{"perspective_search":len(candidates)})
    return eligible


def unused_task(run, phase, index, available):
    write(Path(run)/"outcomes/unused_tasks"/(phase+"_"+str(index)+".json"),{"status":"skipped_unused_slot","index":index,"available_tasks":available,"phase":phase,"scientific_model_called":False})


def salvage_perspective_checkpoints(run):
    """Finalize evaluated checkpoints after interrupted workers, without evaluation."""
    run,config,identity=run_check(run);root=run/"perspective";path=root/"candidates.json"
    recovered=[]
    for candidate in read(path) if path.exists() else []:
        folder=root/"candidates"/candidate["id"];checkpoint=folder/"checkpoint.json";final=folder/"final.json"
        if final.exists() or not checkpoint.exists():continue
        proof_path=folder/"attempt_identity.json"
        if not proof_path.exists():continue
        proof=read(proof_path)
        if proof.get("run_id")!=identity["run_id"] or proof.get("candidate")!=candidate or proof.get("input_manifest_sha256")!=sha(run/"input_manifest.json"):raise SetupError("Interrupted perspective checkpoint is foreign/modified")
        value=read(checkpoint);vector=value.get("x",[]);loss=value.get("loss")
        if not value.get("valid") or not isinstance(loss,(int,float)) or not math.isfinite(loss) or len(vector)!=33 or any(not math.isfinite(v) or not config["perspective"]["bounds"][i][0]-1e-12<=v<=config["perspective"]["bounds"][i][1]+1e-12 for i,v in enumerate(vector)):continue
        value.update(candidate=candidate,status="recovered_interrupted_checkpoint",checkpoint_sha256=sha(checkpoint),recovery_evaluated_model=False)
        write(final,value);recovered.append({"candidate_id":candidate["id"],"checkpoint_sha256":sha(checkpoint),"final_sha256":sha(final)})
    write(root/"audit/checkpoint_recovery.json",{"recovered":recovered,"scientific_calls":0,"time_utc":utc()})
    return recovered


def native_with_reservation(run,config,identity,key,callback):
    import storage_budget
    import native_stream
    directory=Path(run)/'transient'/key
    reserve,commit,release=storage_budget.asset_callbacks(run,config)
    with storage_budget.reserve_case(run,config,key,directory) as limits:
        native_stream.STORAGE_CONTEXT={**limits,'case_directory':str(directory),'trajectory_bytes':262144,'log_bytes':65536,'run_root':str(run),'run_id':identity['run_id'],'input_manifest_sha256':sha(Path(run)/'input_manifest.json'),'recognized_rows':config['storage']['figure_rows'],'figure_rows':config['storage']['figure_rows'],'figure_replicates':config['storage']['figure_replicates'],'reserve_asset':reserve,'commit_asset':commit,'release_asset':release}
        limits['completion_verified']=False
        try:
            result=callback()
            limits['completion_verified']=bool(native_stream.STORAGE_CONTEXT.get('_compact_finalized',False))
            return result
        finally:native_stream.STORAGE_CONTEXT=None


def worker(config, config_path, run, phase, stage, index, trajectory):
    import campaign_budget
    if phase not in {'run-input-check','budget-start','budget-controller','budget-janitor','report-accept'} and not campaign_budget.admitted(run):
        write(Path(run)/'budget/not_started'/(phase+'_'+stage+'_'+str(index)+'_'+str(trajectory)+'.json'),{'status':'not_started_budget','phase':phase,'index':index,'trajectory':trajectory,'scientific_model_called':False,'time_utc':utc()})
        return
    if phase=='budget-start':
        execution_gate(config);run_check(run,config_path)
        state=read(Path(run)/'storage/state.json')
        if not state['inventory'].get('verified'):raise SetupError('Project-wide storage inventory is not verified')
        return campaign_budget.initialize(run,config)
    if phase=='budget-controller':
        execution_gate(config);run_check(run,config_path)
        return campaign_budget.controller(run,config)
    if phase=='budget-janitor':
        execution_gate(config);run_check(run,config_path)
        return campaign_budget.janitor(run,config)
    if phase=='lineage-native-select':
        execution_gate(config);run,frozen,identity=run_check(run,config_path)
        import native_pool
        return native_pool.select(run,frozen,stage)
    if phase in {'lineage-simulate-selected','lineage-score-selected-candidate'}:
        pool_path=Path(run)/'lineage'/(stage+'_native_candidates.json');selected=read(pool_path)
        proof=read(Path(run)/'lineage'/(stage+'_native_selection.json'))
        if proof.get('pool_manifest_sha256')!=sha(pool_path) or proof.get('run_id')!=read(Path(run)/'run_identity.json')['run_id'] or proof.get('input_manifest_sha256')!=sha(Path(run)/'input_manifest.json'):raise SetupError('Native pool provenance mismatch')
        if index>=len(selected):return unused_task(run,phase,index,len(selected))
        entry=selected[index];manifest=Path(run)/'lineage'/(stage+'_candidates.json');original=read(manifest)
        if proof.get('candidate_manifest_sha256')!=sha(manifest) or entry['candidate_index']>=len(original) or original[entry['candidate_index']]['id']!=entry['candidate_id'] or sha(Path(run)/'lineage/candidates'/entry['candidate_id']/'final.json')!=entry['final_sha256']:raise SetupError('Native pool candidate/final mapping changed')
        index=entry['candidate_index'];phase='lineage-simulate' if phase=='lineage-simulate-selected' else 'lineage-score-candidate'
    # Non-scientific preparation is available independently; all science is gated.
    if phase=="lineage-ridge-prepare":
        return prepare_ridge(run)
    if phase=="perspective-prepare":
        result=prepare_perspective(run)
        import scheduler
        scheduler.trim_unused(run,{"perspective_embedding":len(embedding_parents(run))})
        return result
    if phase=="perspective-embedding-finalize":
        return finalize_embeddings(run)
    if phase=="run-input-check":
        run_check(run,config_path)
        return
    if phase=="report-accept":
        if config["execution"]["authorized"] and os.environ.get("SLURM_JOB_ID"):
            execution_gate(config)
            import scheduler
            try:scheduler.collect_accounting(run)
            except Exception as error:write(Path(run)/"report/accounting_error.json",{"error":repr(error),"traceback":traceback.format_exc(),"compute_totals_fabricated":False})
        return report_run(run)
    if phase in {"perspective-screen-select","perspective-native-prepare","perspective-finalist-select"}:
        import terminal
        if phase=="perspective-screen-select":
            salvage_perspective_checkpoints(run)
            return terminal.select_screen(run)
        import scheduler
        if phase=="perspective-native-prepare":
            result=terminal.prepare_native(run,stage)
            selected=read(Path(run)/"perspective"/stage/"candidates.json")
            repeats=config["perspective"]["conditional"].get("refinement_replicates",1)
            write(Path(run)/"perspective/refinement_tasks.json",[{"index":i*repeats+j,"source_index":i,"source_id":candidate["id"],"replicate":j,"attempt_directory":"refinement/"+candidate["id"]+f"/replicate_{j:03}"} for i,candidate in enumerate(selected) for j in range(repeats)])
            scheduler.trim_unused(run,{"perspective_screen_native":len(result),"perspective_screen_diagnostics":len(selected),"perspective_bounded_refinement":len(selected)*repeats})
            return result
        result=terminal.select_finalists(run)
        scheduler.trim_unused(run,{"perspective_final_native":len(read(Path(run)/"perspective/final_validation/slots.json")),"perspective_final_diagnostics":len(result)})
        return result
    execution_gate(config)
    run, frozen, identity=run_check(run,config_path)
    verify_runtime_dependencies(run)
    config=frozen
    # Quotas are upper bounds; avoid scientific imports for unused reserved slots.
    if phase in {"perspective-fit","perspective-embedding-check","perspective-native","perspective-native-analyze","perspective-refine"}:
        if phase=="perspective-embedding-check":available=len(embedding_parents(run))
        else:
            path=run/"perspective"/((stage+"/slots.json") if phase=="perspective-native" else (stage+"/candidates.json") if phase=="perspective-native-analyze" else "screen_candidates.json" if phase=="perspective-refine" else "candidates.json")
            available=len(read(path)) if path.exists() else 0
            if phase=="perspective-refine":available*=config["perspective"]["conditional"].get("refinement_replicates",1)
        if index>=available:return unused_task(run,phase,index,available)
        if phase=="perspective-native":
            stage_root=run/"perspective"/stage;deadline=read(stage_root/"stage_identity.json").get("deadline_unix")
            if deadline is not None and deadline-time.time()<5:
                import terminal
                terminal.verify_native_stage(run,stage)
                slot=read(stage_root/"slots.json")[index];destination=stage_root/"cases"/slot["candidate_id"]/f"{index:05}"
                if destination.exists():raise SetupError("Native case attempt exists; no overwrite")
                write(destination/"outcome.json",{"status":"not_started_deadline","slot":slot,"reason":"relative_native_stage_deadline_exhausted","scientific_model_called":False,"engine_started":False,"wall_seconds":0.})
                return
    os.environ["NUMBA_CACHE_DIR"]=str(run/"cache/numba")
    if phase not in RUNTIME_COMMANDS:
        raise SetupError("Unimplemented perspective terminal policy or dispatcher; see ISSUES.md: "+phase)
    # Compiled code stays in process memory. Disabling only persistence preserves
    # Numba's generated numerical kernels and avoids unbounded per-worker cache copies.
    if not config['storage'].get('jit_disk_cache',False):
        import numba
        if not getattr(numba.njit,'_baseline_no_disk_cache',False):
            original_njit=numba.njit
            def memory_njit(*args,**kwargs):
                kwargs['cache']=False
                return original_njit(*args,**kwargs)
            memory_njit._baseline_no_disk_cache=True
            numba.njit=memory_njit
    sys.path.insert(0,str(PACKAGE/"vendor"))
    from core import fitting as bounded_fitting
    bounded_fitting.ATOMIC_JSON_BYTES_LIMIT=262144 if phase in {"lineage-fit","lineage-finalize","perspective-fit","perspective-refine"} else None
    if phase.startswith("lineage-"):
        import lineage_model as a
        a.ROOT=run/"lineage";a.ENGINE=resolve(config,"lineage_engine")
        a.ALPHAS=config["lineage"]["alphas"];a.REPLICATES=config["lineage"]["replicates"]
        a.NATIVE_SEED_BASE=config["lineage"]["seed_native"]
        a.TIMEOUT=campaign_budget.clip_seconds(run,config["lineage"]["native_timeout_seconds"]);a.OPTIMIZER_SECONDS=campaign_budget.clip_seconds(run,config["lineage"]["optimizer_seconds"]);a.STEPS=config["lineage"]["steps"]
        if phase=="lineage-fit":
            candidate=a.candidate(stage,index)
            directory=a.ROOT/"candidates"/candidate["id"]
            if directory.exists():
                raise SetupError("Candidate attempt exists; automatic overwrite/retry prohibited")
            write(directory/"attempt_identity.json",{"run_id":identity["run_id"],"candidate_id":candidate["id"],"candidate":candidate,"input_manifest_sha256":sha(run/"input_manifest.json"),"started_utc":utc()})
            a.fit(stage,index)
        elif phase=="lineage-finalize":
            candidate=a.candidate(stage,index);directory=a.ROOT/"candidates"/candidate["id"]
            if (directory/"final.json").exists():raise SetupError("Candidate finalization already exists; no overwrite")
            attempt=directory/"attempt_identity.json"
            if not attempt.exists():
                write(directory/"outcome.json",{"status":"missing_current_attempt","candidate_id":candidate["id"],"run_id":identity["run_id"]})
                return
            value=read(attempt)
            if value["run_id"]!=identity["run_id"] or value["candidate"]!=candidate or value["input_manifest_sha256"]!=sha(run/"input_manifest.json"):
                raise SetupError("Candidate attempt does not match this run/configuration")
            a.finalize(stage,index)
            if (directory/"final.json").exists():
                write(directory/"final_provenance.json",{"run_id":identity["run_id"],"candidate_id":candidate["id"],"final_sha256":sha(directory/"final.json"),"input_manifest_sha256":sha(run/"input_manifest.json"),"checkpoint_sha256":sha(directory/"checkpoint.json")})
        elif phase=="lineage-simulate":
            candidate=a.candidate(stage,index)
            directory=a.ROOT/"candidates"/candidate["id"]
            if (directory/"simulations"/f"{trajectory:03}").exists():
                raise SetupError("Trajectory attempt exists; automatic overwrite/retry prohibited")
            provenance=directory/"final_provenance.json"
            if not provenance.exists():
                write(directory/"simulations"/f"{trajectory:03}"/"outcome.json",{"status":"blocked","reason":"missing_current_run_finalization","run_id":identity["run_id"],"candidate_id":candidate["id"]})
                return
            value=read(provenance)
            if value["run_id"]!=identity["run_id"] or value["final_sha256"]!=sha(directory/"final.json"):
                raise SetupError("Trajectory parent finalization is foreign/modified")
            native_with_reservation(run,config,identity,"lineage_"+stage+"_"+str(index)+"_"+str(trajectory),lambda:a.simulate(stage,index,trajectory))
        elif phase=="lineage-score":
            a.score(stage)
            if stage=="shared":
                write(a.ROOT/"shared_score_provenance.json",{"run_id":identity["run_id"],"scores_sha256":sha(a.ROOT/"shared_scores.json"),"input_manifest_sha256":sha(run/"input_manifest.json")})
        elif phase=="lineage-score-candidate":
            candidate=a.candidate(stage,index);directory=a.ROOT/"candidates"/candidate["id"]
            if (directory/"final.json").exists():
                proof=read(directory/"final_provenance.json")
                if proof.get("run_id")!=identity["run_id"] or proof.get("candidate_id")!=candidate["id"] or proof.get("input_manifest_sha256")!=sha(run/"input_manifest.json") or proof.get("final_sha256")!=sha(directory/"final.json"):raise SetupError("Score candidate finalization is foreign/modified")
            a.score_candidate_worker(stage,index)
    else:
        import perspective_model as a
        import perspective_search as e
        a.ROOT=run/"perspective";e.ROOT=a.ROOT;e.SECONDS=campaign_budget.clip_seconds(run,config["perspective"]["optimizer_seconds"])
        a.ALPHAS=config["perspective"]["alphas"];a.STEPS=config["perspective"]["steps"]
        data_class=a.Data
        a.Data=lambda: data_class(steps=config["perspective"]["steps"])
        if phase=="perspective-fit":
            embedding=read(a.ROOT/"embedding_check.json")
            if not embedding.get("passed") or embedding.get("candidates_sha256")!=sha(a.ROOT/"candidates.json") or embedding.get("parents_sha256")!=sha(a.ROOT/"parents.json"):
                raise SetupError("Perspective fit requires finalized numerical parent screening and matching start manifests")
            candidate=read(a.ROOT/"candidates.json")[index]
            if (a.ROOT/"candidates"/candidate["id"]).exists():raise SetupError("Perspective attempt exists; no automatic retry")
            write(a.ROOT/"candidates"/candidate["id"]/"attempt_identity.json",{"candidate":candidate,"run_id":identity["run_id"],"input_manifest_sha256":sha(run/"input_manifest.json"),"started_utc":utc()})
            e.fit(index)
        elif phase=="perspective-embedding-check":
            p=embedding_parents(run)[index]
            result=a.evaluate(a.Data(),__import__("numpy").asarray(p["x"]),0.,"no_wgd")
            expected=p["reference"].get("approximation_data_loss")
            if expected is None and result.get("valid"):
                import lineage_model
                lineage_model.ROOT=run/"lineage";lineage_model.STEPS=config["lineage"]["steps"]
                reference=lineage_model.evaluate(lineage_model.Data(),__import__("numpy").asarray(p["reference"]["x"]),0.)
                expected=reference.get("data_loss") if not reference.get("invalid") else None
            error=abs(result["data_loss"]-expected) if result.get("valid") and expected is not None else None
            write(a.ROOT/"embedding_checks"/(str(index)+".json"),{"parent":p["id"],"parent_sha256":hashlib.sha256(json.dumps(p,sort_keys=True,allow_nan=False).encode()).hexdigest(),"absolute_error":error,"microscopy_agreement":error is not None and error<=1e-9,"valid":bool(result.get("valid")),"evaluation":a.clean(result),"status":"valid" if result.get("valid") else "invalid_model_initialization","finite_differences_are_diagnostic":True})
        else:
            import terminal
            import wgd_transfer
            import native_diagnostics as native
            wgd_transfer.ENGINE=resolve(config,"perspective_engine")
            native.ROOT=a.ROOT;native.a=a;native.native=wgd_transfer
            native.TIMEOUT=campaign_budget.clip_seconds(run,config["perspective"]["native_timeout_seconds"])
            native.SEED=config["perspective"]["seed_native"]
            native.BOOT=config["perspective"]["conditional"]["bootstrap_replicates"]
            native.PROBE_FRACTIONS=config["perspective"]["conditional"]["minority_probe_fractions"]
            if phase in {"perspective-native","perspective-native-analyze"}:terminal.verify_native_stage(run,stage)
            if phase=="perspective-native":
                slots=read(a.ROOT/stage/"slots.json")
                slot=slots[index];directory=a.ROOT/stage/"cases"/slot["candidate_id"]/f"{index:05}"
                if directory.exists():raise SetupError("Native case attempt exists; no overwrite or automatic retry")
                native_with_reservation(run,config,identity,"perspective_"+stage+"_"+str(index),lambda:native.run(stage,index))
            elif phase=="perspective-native-analyze":
                selected=read(a.ROOT/stage/"candidates.json");cid=selected[index]["id"]
                destination=a.ROOT/stage/"analysis"/cid
                if destination.exists():raise SetupError("Native analysis exists; no overwrite")
                try:native.analyze(stage,index)
                except Exception as error:
                    write(destination/"outcome.json",{"status":"failed","candidate_id":cid,"error":repr(error),"traceback":traceback.format_exc(),"scores_fabricated":False})
                    raise
            elif phase=="perspective-refine":
                import native_refinement
                native_refinement.r=a.ROOT;native_refinement.a=a;native_refinement.e=e
                repeats=config["perspective"]["conditional"].get("refinement_replicates",1)
                source_index=index//repeats;replicate=index%repeats
                candidates=read(a.ROOT/"screen_candidates.json");cid=candidates[source_index]["id"]
                destination=a.ROOT/"refinement"/cid/f"replicate_{replicate:03}"
                if destination.exists():raise SetupError("Native-informed refinement attempt exists; no overwrite")
                eligibility=terminal.refinement_eligibility(a.ROOT,candidates[source_index])
                if not eligibility["eligible"]:
                    write(destination/"outcome.json",eligibility)
                    if eligibility["status"]=="failed":raise SetupError("Refinement unavailable: "+eligibility["reason"])
                    return
                try:native_refinement.run(source_index,seconds=campaign_budget.clip_seconds(run,config["perspective"]["conditional"]["refinement_seconds"]),replicate=replicate)
                except Exception as error:
                    write(destination/"outcome.json",{"status":"failed","candidate_id":cid,"error":repr(error),"traceback":traceback.format_exc(),"scores_fabricated":False})
                    raise


def accounting(csv_path, output):
    """Offline sacct export ingestion, never queries SLURM; include failed rows."""
    delimiter="|" if ".psv" in str(csv_path) else ","
    rows=list(csv.DictReader(Path(csv_path).open(),delimiter=delimiter))
    if not rows:raise SetupError("No accounting records; a header alone is not measured compute evidence")
    phases={};intervals=[];latency=[];queue=[];dependency=[]
    def cpu_seconds(value):
        if not value or value in ("Unknown","N/A"):return None
        day,_,clock=value.rpartition("-")
        values=[float(v) for v in (clock if _ else value).split(":")]
        return (float(day)*86400 if _ else 0)+sum(v*60**i for i,v in enumerate(reversed(values)))
    def timestamp(v):
        if not v or v in ("Unknown","N/A","None"):return None
        return datetime.fromisoformat(v.replace("Z","+00:00")).timestamp()
    required={"JobIDRaw","Phase","State","AllocCPUS","ElapsedRaw","TotalCPU","Submit","Start","End"}
    if rows and not required.issubset(rows[0]):
        raise SetupError("Offline accounting export missing columns: "+", ".join(sorted(required-set(rows[0]))))
    seen=set();states={};cpu_missing=0
    for row in rows:
        jid=row["JobIDRaw"]
        if "." in jid or jid in seen:continue  # exclude batch/extern job steps and duplicate exports
        seen.add(jid);phase=row["Phase"]
        if not phase:raise SetupError("Every accounting row requires frozen task-to-phase mapping")
        q=phases.setdefault(phase,{"measured_cpu_hours":0.,"allocated_cpu_hours":0.,"tasks":0,"failed_or_cancelled_tasks":0,"nonterminal_tasks":0})
        used=cpu_seconds(row["TotalCPU"])
        if used is None:cpu_missing+=1
        else:q["measured_cpu_hours"]+=used/3600
        q["allocated_cpu_hours"]+=float(row["ElapsedRaw"])*int(row["AllocCPUS"])/3600;q["tasks"]+=1
        terminal_failures={"FAILED","CANCELLED","TIMEOUT","OUT_OF_MEMORY","NODE_FAIL","PREEMPTED","BOOT_FAIL","DEADLINE"}
        if row["State"] in terminal_failures:q["failed_or_cancelled_tasks"]+=1
        elif row["State"]!="COMPLETED":q["nonterminal_tasks"]+=1
        states[row["State"]]=states.get(row["State"],0)+1
        submit,start,end=map(timestamp,[row["Submit"],row["Start"],row["End"]])
        eligible=timestamp(row.get("Eligible"))
        if start is not None and submit is not None:latency.append(start-submit)
        if eligible is not None and submit is not None and start is not None:queue.append(start-eligible);dependency.append(eligible-submit)
        if start is not None and end is not None:intervals.extend([(start,int(row["AllocCPUS"])),(end,-int(row["AllocCPUS"]))])
    allocated=0;peak=0
    for _,change in sorted(intervals,key=lambda item:(item[0],item[1])):
        allocated+=change;peak=max(peak,allocated)
    result={"phases":phases,"states":states,"failed_attempts_included":True,"measured_cpu_hours":sum(p["measured_cpu_hours"] for p in phases.values()),"allocated_cpu_hours":sum(p["allocated_cpu_hours"] for p in phases.values()),"peak_allocated_cpus":peak,"peak_used_cpus":None,"missing_TotalCPU_rows":cpu_missing,"elapsed_first_start_to_last_end_seconds":max(t for t,d in intervals)-min(t for t,d in intervals) if intervals else None,"mean_submit_to_start_seconds":sum(latency)/len(latency) if latency else None,"mean_eligible_to_start_queue_seconds":sum(queue)/len(queue) if queue else None,"mean_submit_to_eligible_dependency_seconds":sum(dependency)/len(dependency) if dependency else None,"queue_note":"Without Eligible, submit-to-start combines dependency/queue/array waits; allocation is not CPU utilization","accounting_input_sha256":sha(csv_path)}
    write(output,result);return result


def report_run(run):
    """Collect frozen results/diagnostics, then implement the fixed accept-for-now policy."""
    run,config,identity=run_check(run)
    result={"run_id":identity["run_id"],"time_utc":utc(),"package_manifest_sha256":identity["package_manifest_sha256"],"input_manifest_sha256":sha(run/"input_manifest.json"),"baseline_definitions":config["baseline_definitions"],"observation":config["observation"],"scratch_boundary":config["inputs"]["scratch_boundary"],"lineage":{},"perspective":{},"complete_scientific_baseline":False,"compute_usage":None,"scientific_model_called_by_report":False}
    for stage in ("shared","ridge"):
        path=run/"lineage"/(stage+"_scores.json");values=read(path) if path.exists() else [];statuses={}
        for value in values:statuses[value["status"]]=statuses.get(value["status"],0)+1
        native_outcomes={}
        for outcome in (run/"lineage/candidates").glob(stage+"*/simulations/*/outcome.json"):
            state=read(outcome).get("status","unknown");native_outcomes[state]=native_outcomes.get(state,0)+1
        result["lineage"][stage]={"status":"scored" if path.exists() else "not_scored","candidate_outcomes":statuses,"native_case_outcomes":native_outcomes,"fully_supported_candidates":statuses.get("complete",0),"scores_sha256":sha(path) if path.exists() else None,"scores":values}
    lineage_results=run/"lineage/results.json"
    if lineage_results.exists():result["lineage"]["comparison"]=read(lineage_results)
    root=run/"perspective";candidate_path=root/"candidates.json";candidates=read(candidate_path) if candidate_path.exists() else [];outcomes=[]
    for c in candidates:
        directory=root/"candidates"/c["id"];path=directory/"final.json";outcome=directory/"outcome.json"
        value=read(path) if path.exists() else read(outcome) if outcome.exists() else None
        outcomes.append({"candidate_id":c["id"],"parent_run_id":c["parent_run_id"],"parent":c["parent"],"status":value.get("status","checkpoint_or_final") if value else "not_started","microscopy":value.get("data_loss") if value else None,"assay_deviance":value.get("assay_deviance") if value else None,"ridge":value.get("ridge_penalty") if value else None,"closure_guidance":value.get("assumption_penalty") if value else None,"native_ranked":False})
    native={}
    for stage in ("screen","final_validation"):
        stage_root=root/stage;path=stage_root/"candidates.json";selected=read(path) if path.exists() else [];diagnostics=[];case_outcomes={}
        for path in sorted((stage_root/"cases").glob("*/*/outcome.json")):
            value=read(path);status=value.get("status","unknown");case_outcomes[status]=case_outcomes.get(status,0)+1
        for c in selected:
            directory=stage_root/"analysis"/c["id"];summary=directory/"summary.json";data=directory/"report_data.json";failure=directory/"outcome.json"
            diagnostics.append({"candidate_id":c["id"],"summary":read(summary) if summary.exists() else None,"report_data":read(data) if data.exists() else None,"failure":read(failure) if failure.exists() else None,"status":"available" if summary.exists() else "failed" if failure.exists() else "unavailable"})
        contract=stage_root/"contract.json"
        native[stage]={"contract":read(contract) if contract.exists() else None,"diagnostics":diagnostics,"case_outcomes":case_outcomes,"requested_cases":read(contract)["total_cases"] if contract.exists() else None,"recorded_case_outcomes":sum(case_outcomes.values())}
    finalist_path=root/"finalists.json";finalists=read(finalist_path) if finalist_path.exists() else []
    refinement=[]
    refinement_dirs=sorted({p.parent for p in (root/"refinement").glob("**/final.json")}|{p.parent for p in (root/"refinement").glob("**/outcome.json")})
    for directory in refinement_dirs:
        final=directory/"final.json";outcome=directory/"outcome.json"
        refinement.append({"attempt_directory":str(directory.relative_to(root)),"candidate_id":read(final).get("candidate",{}).get("id") if final.exists() else directory.parent.name,"status":"completed" if final.exists() else read(outcome).get("status","unknown") if outcome.exists() else "unavailable","outcome":read(outcome) if outcome.exists() else None})
    final_native=native["final_validation"]
    def complete_diagnostic(diagnostic):
        value=diagnostic["summary"] or {};loss=value.get("native_microscopy_loss")
        return value.get("status")=="complete" and value.get("correction_status")=="available" and not value.get("failures") and isinstance(loss,(int,float)) and math.isfinite(loss) and value.get("main_complete",0)==value.get("main_requested",-1) and value.get("probes_complete",0)==value.get("probes_requested",-1)
    diagnostics_complete=bool(finalists) and len(final_native["diagnostics"])==len(finalists) and all(complete_diagnostic(d) for d in final_native["diagnostics"]) and final_native["recorded_case_outcomes"]==final_native["requested_cases"] and final_native["case_outcomes"].get("complete",0)==final_native["requested_cases"]
    quota_complete=len(finalists)==config["perspective"]["conditional"]["finalists"]
    acceptance={"policy":config["execution"]["acceptance_policy"],"decision":"accept_for_now" if finalists else "unavailable_no_valid_terminal_fit","validation_status":"complete" if diagnostics_complete else "incomplete" if finalists else "unavailable","search_breadth_degraded":not quota_complete,"terminal_fit_available":bool(finalists),"quality_threshold_applied":False,"additional_correction":False,"refit_triggered":False,"additional_native_batch_triggered":False,"diagnostics_do_not_change_frozen_physical_parameters":True}
    parent_path=root/"parents.json";embedding_path=root/"embedding_check.json"
    result["perspective"]={"terminal_policy":config["execution"]["terminal_policy"],"terminal_workers_implemented":True,"parents":read(parent_path) if parent_path.exists() else None,"embedding":read(embedding_path) if embedding_path.exists() else None,"exploratory_outcomes":outcomes,"refinement_outcomes":refinement,"finalists":finalists,"requested_finalist_quota":config["perspective"]["conditional"]["finalists"],"actual_finalists":len(finalists),"native":native,"acceptance":acceptance,"selection_audit":read(root/"audit/finalist_selection.json") if (root/"audit/finalist_selection.json").exists() else None}
    result["complete_scientific_baseline"]=diagnostics_complete and quota_complete and all(result["lineage"][stage]["fully_supported_candidates"]>0 for stage in ("shared","ridge"))
    result["degraded_evidence"]=not result["complete_scientific_baseline"]
    result["budget_terminal"]=read(run/"budget_terminal.json") if (run/"budget_terminal.json").exists() else None
    saved=result["budget_terminal"] or {}
    acceptance["saved_fit_count"]=saved.get("selected_fit_count",0)
    acceptance["saved_perspective_fit_count"]=len(saved.get("perspective",{}).get("selected",[]))
    acceptance["saved_lineage_fit_count"]=sum(len(saved.get("lineage",{}).get(stage,{}).get("selected",[])) for stage in ("shared","ridge"))
    acceptance["saved_fit_available"]=acceptance["saved_perspective_fit_count"]>0
    if not finalists and acceptance["saved_fit_available"]:
        acceptance.update(decision="accept_saved_fit_for_now",validation_status="incomplete_saved_evidence",terminal_fit_available=True)
    acceptance["full_scientific_completion"]=result["complete_scientific_baseline"]
    result["execution_budget"]=read(run/"budget/clock.json") if (run/"budget/clock.json").exists() else None
    result["storage_plan"]=read(run/"storage/plan.json") if (run/"storage/plan.json").exists() else None
    records=[]
    for path in sorted((run/"accounting").glob("*.json")):
        value=read(path);records.append(value)
    by_phase={}
    for value in records:
        key=value["phase"];entry=by_phase.setdefault(key,{"recorded_worker_attempts":0,"measured_worker_cpu_hours":0.,"failed_attempts":0})
        entry["recorded_worker_attempts"]+=1;entry["measured_worker_cpu_hours"]+=(value.get("self_cpu_seconds",0.)+value.get("child_cpu_seconds",0.))/3600
        entry["failed_attempts"]+=value["status"]!="complete"
    result["worker_compute_usage"]={"phases":by_phase,"measured_worker_cpu_hours":sum(e["measured_worker_cpu_hours"] for e in by_phase.values()),"allocated_SLURM_cpu_hours":None,"note":"RUSAGE_SELF + completed RUSAGE_CHILDREN within each worker, including failed attempts; excludes interpreter startup before worker and current report worker until it returns. Full allocation/queue accounting requires offline scheduler export."}
    usage=run/"report/compute_usage.json"
    if usage.exists():result["compute_usage"]=read(usage)
    output=run/"report";write(output/"results.json",result);write(output/"acceptance.json",acceptance)
    text=["# Baseline evidence report","","Run: "+identity["run_id"],"","Decision: "+acceptance["decision"]+"; independent validation status: "+acceptance["validation_status"]+".","","The fixed protocol ends here. Diagnostics do not trigger another correction, refit, or native batch. Failed and unavailable tasks remain in results.json; missing scores are not fabricated.","","Scratch boundary: "+config["inputs"]["scratch_boundary"],"","Lineage-determined: "+config["baseline_definitions"]["lineage_determined"],"","Perspective-guided: "+config["baseline_definitions"]["perspective_guided"],"","Observation: 30 columns, six components; total retained and dead counts are distinct. Replicate losses are scored separately and averaged.","","| Phase | Status | Outcomes |","| --- | --- | --- |"]
    for stage in ("shared","ridge"):
        value=result["lineage"][stage];text.append("| lineage "+stage+" | "+value["status"]+" | "+json.dumps(value["candidate_outcomes"])+" |")
    for stage,value in native.items():text.append("| perspective "+stage+" | "+str(len(value["diagnostics"]))+" candidate diagnostics | "+json.dumps(value["case_outcomes"])+" |")
    text += ["","Saved-fit availability by baseline: lineage="+str(acceptance["saved_lineage_fit_count"])+", perspective="+str(acceptance["saved_perspective_fit_count"])+". A lineage-only checkpoint does not establish a perspective fit.","","Finalists retained: "+str(len(finalists))+" of configured quota "+str(config["perspective"]["conditional"]["finalists"])+". Degraded evidence: "+str(result["degraded_evidence"])+".","","Ranking bases: "+json.dumps([{key:c.get(key) for key in ("id","source_id","ranking_basis","native_support")} for c in finalists])+". Partial native objectives and approximation fallbacks are labeled separately; missing components and trajectories are never assigned zero loss."]
    text += ["","Microscopy, assay deviance, ridge regularization, closure guidance, projected composition diagnostics and source hashes remain separate in results.json. Final diagnostics keep the physical parameter vector fixed.","","Measured worker CPU-hours: "+str(result["worker_compute_usage"]["measured_worker_cpu_hours"])+". Full measured-versus-allocated SLURM accounting: "+("attached in compute_usage.json" if result["compute_usage"] is not None else "not supplied; no allocation or queue measurements inferred"),"","This report only reads saved evidence. It invokes no scientific model, optimizer, simulator or scheduler.",""]
    (output/"REPORT.md").write_text("\n".join(text))
    return output/"REPORT.md"


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",nargs="?",default="dry-run",choices=["dry-run","preflight","prepare","freeze","worker","accounting","report","mock","scheduler-plan","submit","dispatch"])
    parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--output",type=Path,default=None)
    parser.add_argument("--run-name");parser.add_argument("--run",type=Path)
    parser.add_argument("--phase");parser.add_argument("--stage",choices=["shared","ridge","screen","final_validation"],default="shared")
    parser.add_argument("--index",type=int,default=0);parser.add_argument("--trajectory",type=int,default=0)
    parser.add_argument("--accounting-csv",type=Path)
    parser.add_argument("--manifest",type=Path)
    parser.add_argument("--manifest-sha256")
    args=parser.parse_args(argv)
    if args.command in {"worker","dispatch"}:resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    try:
        config=load_config(args.config)
        if args.output is None:args.output=resolve(config,"scratch_root")/"planning"
        if args.command in {"dry-run","preflight"}:
            if not inside(args.output,resolve(config,"scratch_root")):raise SetupError("Validation output must remain inside configured scratch_root")
            check=preflight(config,args.config)
            write(args.output/"preflight.json",check)
            if args.command=="dry-run":
                dependency=dependency_plan(config,args.config,check)
                write(args.output/"dependency_plan.json",dependency)
                if dependency.get("scheduler_specification"):
                    import scheduler
                    scheduler.plan(dependency["scheduler_specification"],args.output/"scheduler",materialize=True)
            print(json.dumps({"setup_valid":check["setup_valid"],"execution_ready":check["execution_ready"],"output":str(args.output),"errors":check["errors"],"execution_blockers":check["execution_blockers"],"jobs_submitted":0,"fits_or_simulations_run":0},indent=2))
            return 0 if check["setup_valid"] and (args.command=="dry-run" or check["execution_ready"]) else 2
        if args.command=="freeze":freeze_package();print(PACKAGE/"source_manifest.json")
        elif args.command=="prepare":print(prepare(config,args.config,args.run_name))
        elif args.command=="worker":
            if args.run is None or args.phase is None:raise SetupError("worker requires --run and --phase")
            started=time.monotonic();before=resource.getrusage(resource.RUSAGE_SELF);before_children=resource.getrusage(resource.RUSAGE_CHILDREN);status="failed";failure=None;failure_trace=None
            try:worker(config,args.config,args.run,args.phase,args.stage,args.index,args.trajectory);status="complete"
            except BaseException as error:
                failure=repr(error);failure_trace=traceback.format_exc();raise
            finally:
                after=resource.getrusage(resource.RUSAGE_SELF)
                after_children=resource.getrusage(resource.RUSAGE_CHILDREN)
                record={"phase":args.phase,"stage":args.stage,"index":args.index,"trajectory":args.trajectory,"status":status,"elapsed_seconds":time.monotonic()-started,"self_cpu_seconds":after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,"child_cpu_seconds":after_children.ru_utime+after_children.ru_stime-before_children.ru_utime-before_children.ru_stime,"includes_engine_child_cpu":True,"SLURM_JOB_ID":os.environ.get("SLURM_JOB_ID"),"SLURM_ARRAY_TASK_ID":os.environ.get("SLURM_ARRAY_TASK_ID"),"time_utc":utc()}
                if failure is not None:record.update(error=failure,traceback=failure_trace)
                if args.run.is_dir() and inside(args.run,resolve(config,"output_root")):
                    write(args.run/"accounting"/(f"{args.phase}_{args.stage}_{args.index}_{args.trajectory}_{time.time_ns()}.json"),record)
        elif args.command=="accounting":
            if args.accounting_csv is None:raise SetupError("accounting requires --accounting-csv")
            if not inside(args.output,resolve(config,"scratch_root")):raise SetupError("Accounting output must remain inside configured scratch_root")
            print(json.dumps(accounting(args.accounting_csv,args.output/"compute_usage.json"),indent=2))
        elif args.command=="report":
            if args.run is None:raise SetupError("report requires --run")
            print(report_run(args.run))
        elif args.command in {"scheduler-plan","submit"}:
            if args.run is None:raise SetupError(args.command+" requires a prepared --run")
            run,config,_=run_check(args.run,args.config)
            check=preflight(config,args.config)
            if not check["setup_valid"]:raise SetupError("Setup preflight failed before scheduler planning")
            import scheduler
            spec=scheduler.campaign_spec(config,args.config,run,check["prepared_data"])
            if args.command=="scheduler-plan":
                plan=scheduler.plan(spec,args.output,materialize=True)
                print(json.dumps({"submitted":False,"tasks":plan["total_array_tasks"],"output":str(args.output),"no_scheduler_calls":True},indent=2))
            else:print(json.dumps(scheduler.submit(spec,args.output),indent=2))
        elif args.command=="dispatch":
            if args.manifest is None:raise SetupError("dispatch requires --manifest")
            if args.manifest_sha256 is None:raise SetupError("dispatch requires the frozen --manifest-sha256")
            import scheduler
            return scheduler.dispatch(args.manifest,int(os.environ.get("SLURM_ARRAY_TASK_ID","0")),args.manifest_sha256)
        elif args.command=="mock":
            import mock_validation
            mock_validation.main(args.output)
        return 0
    except (SetupError,FileNotFoundError,ValueError) as error:
        print("SETUP BLOCKED: "+str(error),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
