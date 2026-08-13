#!/usr/bin/env python3
"""Prepare isolated notebook-compression packets and a SLURM deployment config."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"{label} is not a file: {path}")


def get_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be an object")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_extractor(path: Path) -> tuple[ModuleType, Callable[[Path], str]]:
    spec = importlib.util.spec_from_file_location("ingest_lab_records_html_extractor", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load HTML extractor: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function = getattr(module, "extract_page", None)
    if not callable(function):
        raise SystemExit(f"HTML extractor must define extract_page(Path) -> str: {path}")
    return module, function


def segment_text(text: str) -> list[dict[str, str]]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not blocks:
        raise SystemExit("HTML extractor returned no nonempty text spans")
    if len(blocks) > 9999:
        raise SystemExit("notebook has more than 9,999 text spans")
    return [
        {"source_span": f"S{index:04d}", "text": block}
        for index, block in enumerate(blocks, start=1)
    ]


def text_metrics(text: str) -> dict[str, int]:
    return {
        "utf8_bytes": len(text.encode("utf-8")),
        "characters": len(text),
        "non_whitespace_characters": len(re.sub(r"\s", "", text)),
        "words": len(re.findall(r"\S+", text)),
        "lines": len(text.splitlines()),
    }


def main() -> None:
    args = parse_args()
    request_path = args.request.resolve()
    request = get_mapping(load_json(request_path), "request")
    if request.get("schema_version") != 1:
        raise SystemExit("request.schema_version must be 1")

    project_root = resolve(Path.cwd(), str(request.get("project_root", ".")))
    if not project_root.is_dir():
        raise SystemExit(f"project_root is not a directory: {project_root}")
    run_dir = resolve(project_root, str(request.get("run_dir", "")))
    if run_dir == project_root or project_root not in run_dir.parents:
        raise SystemExit("run_dir must be a new directory below project_root")
    if run_dir.exists():
        raise SystemExit(f"refusing to reuse run_dir: {run_dir}")

    notebooks = request.get("notebooks")
    if not isinstance(notebooks, list) or not notebooks:
        raise SystemExit("notebooks must be a nonempty array")
    notebook_specs: list[tuple[str, Path]] = []
    for index, value in enumerate(notebooks):
        spec = get_mapping(value, f"notebooks[{index}]")
        notebook_id = spec.get("notebook_id")
        source_html = spec.get("source_html")
        if not isinstance(notebook_id, str) or not TASK_ID_RE.fullmatch(notebook_id):
            raise SystemExit(f"notebooks[{index}].notebook_id is not filesystem-safe")
        if not isinstance(source_html, str) or not source_html:
            raise SystemExit(f"notebooks[{index}].source_html must be a nonempty string")
        html_path = resolve(project_root, source_html)
        require_file(html_path, f"notebooks[{index}].source_html")
        notebook_specs.append((notebook_id, html_path))
    notebook_ids = [value[0] for value in notebook_specs]
    if len(notebook_ids) != len(set(notebook_ids)):
        raise SystemExit("notebooks contains duplicate notebook IDs")

    sources = get_mapping(request.get("sources"), "sources")
    extractor_path = resolve(project_root, str(sources.get("html_text_extractor", "")))
    require_file(extractor_path, "sources.html_text_extractor")
    _, extract_page = load_extractor(extractor_path)

    context = get_mapping(request.get("context"), "context")
    workflow_reference = resolve(project_root, str(context.get("workflow_reference", "")))
    require_file(workflow_reference, "context.workflow_reference")
    agent = get_mapping(request.get("agent"), "agent")
    slurm = get_mapping(request.get("slurm"), "slurm")

    skill_dir = Path(__file__).resolve().parent.parent
    internal_assets = {
        "prompt": skill_dir / "assets" / "notebook-compression-prompt.txt",
        "schema": skill_dir / "assets" / "notebook-compression-output.schema.json",
        "launcher": skill_dir / "scripts" / "deploy-template.sh",
        "renderer": skill_dir / "scripts" / "render-task-prompt.py",
        "evaluator": skill_dir / "scripts" / "evaluate-notebook-compression.py",
    }
    for key, path in internal_assets.items():
        require_file(path, f"skill {key}")

    (run_dir / "inputs" / "notebooks").mkdir(parents=True)
    (run_dir / "context").mkdir()
    (run_dir / "runtime").mkdir()
    (run_dir / "logs").mkdir()

    copied = {
        "workflow_reference": run_dir / "context" / "notebook-compression.md",
        "prompt": run_dir / "runtime" / "prompt.txt",
        "schema": run_dir / "runtime" / "output.schema.json",
        "launcher": run_dir / "runtime" / "deploy-template.sh",
        "renderer": run_dir / "runtime" / "render-task-prompt.py",
        "evaluator": run_dir / "runtime" / "evaluate-notebook-compression.py",
    }
    shutil.copy2(workflow_reference, copied["workflow_reference"])
    for key in ("prompt", "schema", "launcher", "renderer", "evaluator"):
        shutil.copy2(internal_assets[key], copied[key])

    tasks: list[dict[str, Any]] = []
    packet_paths: list[Path] = []
    external_sources = [extractor_path]
    for notebook_id, html_path in notebook_specs:
        extracted_text = extract_page(html_path)
        if not isinstance(extracted_text, str) or not extracted_text.strip():
            raise SystemExit(f"extractor returned no text for {notebook_id}: {html_path}")
        segments = segment_text(extracted_text)
        packet = {
            "schema_version": 1,
            "notebook_id": notebook_id,
            "source_provenance": {
                "source_html": str(html_path),
                "source_html_sha256": sha256_file(html_path),
                "html_text_extractor": str(extractor_path),
                "html_text_extractor_sha256": sha256_file(extractor_path),
                "extracted_text_sha256": sha256_bytes(extracted_text.encode("utf-8")),
            },
            "source_metrics": text_metrics(extracted_text),
            "source_span_count": len(segments),
            "source_segments": segments,
        }
        packet_path = run_dir / "inputs" / "notebooks" / f"{notebook_id}.json"
        write_json(packet_path, packet)
        packet_paths.append(packet_path)
        external_sources.append(html_path)
        tasks.append(
            {
                "task_id": notebook_id,
                "workflow": "notebook-compression",
                "notebook_id": notebook_id,
                "workflow_reference": str(copied["workflow_reference"]),
                "notebook_packet": str(packet_path),
            }
        )

    tasks_path = run_dir / "tasks.jsonl"
    tasks_path.write_text("".join(json.dumps(task, sort_keys=True) + "\n" for task in tasks), encoding="utf-8")

    codex_bin = agent.get("codex_bin", "codex")
    model = agent.get("model")
    reasoning = agent.get("reasoning")
    sandbox = agent.get("sandbox", "read-only")
    approval_policy = agent.get("approval_policy", "never")
    if not all(isinstance(value, str) and value for value in (codex_bin, model, reasoning, sandbox, approval_policy)):
        raise SystemExit("agent settings must be nonempty strings")
    if sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
        raise SystemExit("agent.sandbox is invalid")

    cpus = slurm.get("cpus", 2)
    concurrency = slurm.get("array_concurrency")
    if not isinstance(cpus, int) or cpus < 1:
        raise SystemExit("slurm.cpus must be a positive integer")
    if concurrency is not None and (not isinstance(concurrency, int) or concurrency < 1):
        raise SystemExit("slurm.array_concurrency must be null or a positive integer")
    extra_args = slurm.get("extra_args", [])
    if not isinstance(extra_args, list) or any(not isinstance(value, str) for value in extra_args):
        raise SystemExit("slurm.extra_args must be an array of strings")

    deploy_config = {
        "schema_version": 1,
        "project_root": str(project_root),
        "run_dir": str(run_dir),
        "tasks_jsonl": str(tasks_path),
        "prompt_template": str(copied["prompt"]),
        "prompt_renderer": str(copied["renderer"]),
        "output_schema": str(copied["schema"]),
        "agent": {
            "codex_bin": codex_bin,
            "model": model,
            "reasoning": reasoning,
            "sandbox": sandbox,
            "approval_policy": approval_policy,
        },
        "slurm": {
            "job_name": slurm.get("job_name", "notebook_compression"),
            "time": slurm.get("time", "00:45:00"),
            "memory": slurm.get("memory", "8G"),
            "cpus": cpus,
            "qos": slurm.get("qos", "small"),
            "partition": slurm.get("partition"),
            "account": slurm.get("account"),
            "array_concurrency": concurrency,
            "extra_args": extra_args,
        },
    }
    write_json(run_dir / "deploy-config.json", deploy_config)

    resolved_request = dict(request)
    resolved_request["project_root"] = str(project_root)
    resolved_request["run_dir"] = str(run_dir)
    resolved_request["notebooks"] = [
        {"notebook_id": notebook_id, "source_html": str(html_path)}
        for notebook_id, html_path in notebook_specs
    ]
    resolved_request["sources"] = {"html_text_extractor": str(extractor_path)}
    resolved_request["context"] = {"workflow_reference": str(workflow_reference)}
    write_json(run_dir / "request.resolved.json", resolved_request)

    hashed_paths = [tasks_path, *copied.values(), *packet_paths]
    unique_sources = sorted(set(external_sources))
    context_manifest = {
        "schema_version": 1,
        "files": [
            {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in sorted(hashed_paths)
        ],
        "external_sources": [
            {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in unique_sources
        ],
    }
    write_json(run_dir / "context_manifest.json", context_manifest)

    print(f"Prepared {len(tasks)} notebook-compression task(s) in {run_dir}")
    print(f"Dry run: DRY_RUN=1 bash {copied['launcher']} {run_dir / 'deploy-config.json'}")
    print(f"Launch:  bash {copied['launcher']} {run_dir / 'deploy-config.json'}")


if __name__ == "__main__":
    main()
