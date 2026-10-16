"""Source-only relocation/privacy checks, with no model or engine invocation."""
from pathlib import Path
import importlib.util
import shutil

import workflow as w


def run(out,check):
    forbidden=["/"+name+"/" for name in ["home","app","share"]]
    files=[p for p in w.PACKAGE.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    check("public_package_has_no_private_data_or_binary_payload",not any(p.suffix in {".npz",".npy",".pkl",".source",".so",".pyc"} or p.read_bytes().startswith(b"\x7fELF") for p in files))
    check("public_package_has_no_machine_installation_paths",not any(token in p.read_text() for p in files for token in forbidden))
    runtime=[p for p in (w.PACKAGE/"vendor").rglob("*.py")]
    check("public_runtime_has_no_historical_run_path_dependencies",not any("hypothesis_tests" in p.read_text() or "scripted_baseline_setup_" in p.read_text() for p in runtime))
    score=(w.PACKAGE/"vendor/core/fitting.py").read_text()
    check("public_observer_retains30_columns_and6_components","p.shape[1] != 30" in score and "w.shape != (len(p),6)" in score)
    clone=Path(out)/"relocated_source_tree"
    package=clone/".codex/skills/physicell-modeling/scripts/baselines"
    shutil.copytree(w.PACKAGE,package,ignore=shutil.ignore_patterns("__pycache__","*.pyc"))
    repo=w.PACKAGE.parents[4]
    for name in ["scripts/run_baselines.py","examples/sum159/baseline.json"]:
        target=clone/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(repo/name,target)
    spec=importlib.util.spec_from_file_location("relocated_baseline_workflow",package/"workflow.py")
    relocated=importlib.util.module_from_spec(spec);spec.loader.exec_module(relocated)
    check("public_source_hashes_verify_after_relocation",relocated.verify_package()==w.verify_package())
    config_path=clone/"examples/sum159/baseline.json";config=relocated.load_config(config_path)
    check("relative_config_paths_resolve_from_config_directory",relocated.resolve(config,"scratch_root")==clone/"tmp/baselines")
    result=relocated.preflight(config,config_path)
    check("relocated_default_reports_missing_inputs_without_model_calls",not result["setup_valid"] and any("paths.prepared_data" in error for error in result["errors"]) and result["scientific_modules_imported"]==[] and result["fits_or_simulations_run"]==0)
