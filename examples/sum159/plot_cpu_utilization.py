#!/usr/bin/env python3
"""Read-only SLURM collection and replay of the realized baseline campaign.

This file is deliberately outside the frozen scientific package. It never starts
an optimizer, simulation, or scheduler job. See METHOD.md for the replay contract.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import heapq
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile


TERMINAL = {
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL",
    "PREEMPTED", "BOOT_FAIL", "DEADLINE", "REVOKED", "SPECIAL_EXIT",
}
CATEGORIES = [
    ("Lineage search", "#4c78a8"),
    ("Lineage simulations", "#72b7b2"),
    ("Perspective search", "#f58518"),
    ("Screen simulations", "#eeca3b"),
    ("Local refinement", "#b279a2"),
    ("Validation simulations", "#54a24b"),
    ("Preparation, analysis and report", "#9d9da1"),
]


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def write_csv(path, rows, fields=None):
    rows = list(rows)
    fields = fields or (list(rows[0]) if rows else [])
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def seconds(value):
    value = str(value or "0")
    days, clock = value.split("-", 1) if "-" in value else ("0", value)
    parts = [float(p) for p in clock.split(":")]
    return int(days) * 86400 + sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


def timestamp(value):
    if not value or value in {"Unknown", "N/A", "None"}:
        return None
    parsed = dt.datetime.fromisoformat(value)
    # Collector sets TZ=UTC explicitly. An offline file must use the same contract.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def category(phase):
    if phase.startswith("lineage_"):
        if phase.endswith(".simulate"):
            return "Lineage simulations"
        if phase.endswith((".fit", ".finalize")):
            return "Lineage search"
    return {
        "perspective_search": "Perspective search",
        "perspective_screen_native": "Screen simulations",
        "perspective_bounded_refinement": "Local refinement",
        "perspective_final_native": "Validation simulations",
    }.get(phase, "Preparation, analysis and report")


def collect(run, out, ancillary_jobs):
    jobs = read_json(run / "scheduler/jobs.json")
    ids = list(jobs.values()) + list(ancillary_jobs)
    command = ["sacct", "-j", ",".join(ids),
               "--format=JobID%100,JobIDRaw,State%40,AllocCPUS,ElapsedRaw,TotalCPU,Submit,Eligible,Start,End,ExitCode", "-P"]
    env = dict(os.environ, TZ="UTC", SLURM_TIME_FORMAT="standard")
    result = subprocess.run(command, text=True, capture_output=True, check=True, env=env)
    (out / "slurm_accounting_utc.psv").write_text(result.stdout)
    write_json(out / "collection.json", {
        "collected_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "command": command, "environment": {"TZ": "UTC", "SLURM_TIME_FORMAT": "standard"},
        "ancillary_jobs": list(ancillary_jobs), "stderr": result.stderr,
    })


def expanded_rows(rows, exclusions):
    """Expand never-started terminal array ranges without multiplying CPU cost."""
    for row in rows:
        key = row.get("JobID", "")
        if "[" not in key:
            yield row
            continue
        state = row.get("State", "").split()[0].rstrip("+")
        if state not in TERMINAL:
            exclusions["unexpanded_pending_array_range"] += 1
            continue
        match = re.fullmatch(r"(\d+)_\[(.+)\]", key)
        if not match:
            raise ValueError("Unsupported terminal array range: " + key)
        if seconds(row.get("TotalCPU")) or float(row.get("ElapsedRaw") or 0) or int(row.get("AllocCPUS") or 0):
            raise ValueError("Nonzero aggregate array-range cost cannot be assigned to individual slots: " + key)
        indices = []
        for part in match.group(2).split("%", 1)[0].split(","):
            bounds = [int(value) for value in part.split("-")]
            indices.extend(range(bounds[0], bounds[-1] + 1))
        exclusions["zero_cost_terminal_range_records_expanded"] += 1
        exclusions["logical_slots_from_terminal_ranges"] += len(indices)
        for index in indices:
            yield dict(row, JobID=match.group(1) + "_" + str(index),
                       # A range has no per-task physical ID. Its aggregate raw ID
                       # may equal a materialized sibling's ID; never use it for
                       # matching that sibling's worker CPU sidecar.
                       JobIDRaw="", SourceArrayRange=key,
                       SourceArrayRangeRawJobID=row.get("JobIDRaw", ""))


def task_contexts(node):
    """Resolve logical slots once, including sparse native groups and score DAGs."""
    contexts = {}
    for group in node["manifest_value"]["task_groups"]:
        sparse = group.get("indices")
        indices = list(sparse) if sparse is not None else list(range(group["first"], group["last"] + 1))
        trajectories = group.get("trajectory_indices")
        if trajectories is not None and len(trajectories) != len(indices):
            raise ValueError("Sparse trajectory mapping has the wrong length: " + node["name"])
        if trajectories is not None and (len(set(trajectories)) != len(trajectories) or
                                          any(type(value) is not int or value < 0 for value in trajectories)):
            raise ValueError("Sparse trajectory mapping is not a unique nonnegative index list: " + node["name"])
        parents = list(group.get("parents", []))
        if group.get("parent") is not None:
            parents.append(group["parent"])
        parents = list(dict.fromkeys(parents))
        if any(type(parent) is not int or not 0 <= parent < node["tasks"] for parent in parents):
            raise ValueError("Parent index outside the frozen node: " + node["name"])
        for position, index in enumerate(indices):
            if type(index) is not int or not 0 <= index < node["tasks"]:
                raise ValueError("Logical index outside the frozen node: " + node["name"])
            if index in contexts:
                raise ValueError("Overlapping frozen task groups: " + node["name"] + "_" + str(index))
            if index in parents:
                raise ValueError("Task depends on itself: " + node["name"] + "_" + str(index))
            context = {"phase": group["phase"], "parent_index": group.get("parent"),
                       "parent_indices": parents.copy(),
                       "candidate_index": group.get("candidate") if group.get("candidate") is not None else index,
                       "trajectory_index": ((trajectories[position] if trajectories is not None else position)
                                            if group["phase"] == "simulate" else None)}
            if group.get("source_candidate_index") is not None:
                context["source_candidate_index"] = group["source_candidate_index"]
                if node["name"] == "perspective_bounded_refinement":
                    context["refinement_replicate"] = position
            contexts[index] = context
    if set(contexts) != set(range(node["tasks"])):
        raise ValueError("Frozen task groups leave uncovered logical slots: " + node["name"])
    return contexts


def normalize(run, raw_path, ancillary_jobs):
    plan = read_json(run / "scheduler/plan.json")
    jobs = read_json(run / "scheduler/jobs.json")
    expected = {}
    node_keys = {}
    for node in plan["nodes"]:
        keys = []
        job = str(jobs[node["name"]])
        contexts = task_contexts(node)
        for index in range(node["tasks"]):
            key = job + ("_" + str(index) if node["tasks"] > 1 else "")
            context = contexts[index]
            phase = node["name"] + ("." + context["phase"] if node["kind"] == "stream" else "")
            expected[key] = {
                "key": key, "node": node["name"], "index": index, "phase": phase,
                "node_reserved_tasks": node["tasks"],
                "category": category(phase), **{field: value for field, value in context.items() if field != "phase"},
                "depends_on": node.get("depends_on"), "state": "NOT_ACCOUNTED",
            }
            keys.append(key)
        node_keys[node["name"]] = keys
    exclusions = collections.Counter()
    unmapped = []
    ancillary = []
    seen = set()
    with Path(raw_path).open() as stream:
        for row in expanded_rows(csv.DictReader(stream, delimiter="|"), exclusions):
            key = row.get("JobID", "")
            if "." in key:
                exclusions["batch_or_extern_step"] += 1
                continue
            if key in ancillary_jobs:
                ancillary.append(row)
                continue
            if key not in expected:
                if key in {str(v) for v in jobs.values()}:
                    exclusions["array_parent_aggregate"] += 1
                else:
                    unmapped.append(key)
                continue
            if key in seen:
                raise ValueError("Duplicate logical task row; attempts must be disambiguated: " + key)
            seen.add(key)
            task = expected[key]
            task.update({
                "raw_job_id": row.get("JobIDRaw", ""),
                "source_array_range": row.get("SourceArrayRange", ""),
                "state": row["State"].split()[0].rstrip("+"),
                "exit_code": row.get("ExitCode", ""),
                "cpus": int(row.get("AllocCPUS") or 0),
                "elapsed_seconds": float(row.get("ElapsedRaw") or 0),
                "cpu_seconds": seconds(row.get("TotalCPU")),
                **{label.lower() + "_utc": row.get(label, "") for label in ["Submit", "Eligible", "Start", "End"]},
            })
            task["start"] = timestamp(row.get("Start"))
            task["end"] = timestamp(row.get("End"))
            task["submit"] = timestamp(row.get("Submit"))
            interval = max(0., (task["end"] - task["start"]) if task["end"] is not None and task["start"] is not None else 0.)
            task["duration_seconds"] = max(interval, task["elapsed_seconds"])
    return list(expected.values()), plan, node_keys, {
        "excluded_row_counts": dict(exclusions), "unmapped_job_ids": unmapped,
        "expected_tasks": len(expected), "accounted_task_rows": len(seen),
        "nonterminal_tasks": [t["key"] for t in expected.values() if t["state"] not in TERMINAL],
        "ancillary_rows": ancillary,
    }


def enrich_tasks(run, tasks):
    """Attach saved candidate/support identity without importing scientific code."""
    cache = {}
    def load(relative):
        if relative not in cache:
            path = run / relative
            cache[relative] = read_json(path) if path.exists() else None
        return cache[relative]
    for task in tasks:
        node = task["node"]
        index = task["candidate_index"]
        slot = None
        native_outcome = None
        if node in {"lineage_shared_stream", "lineage_ridge_stream"}:
            stage = "shared" if "shared" in node else "ridge"
            candidates = load(f"lineage/{stage}_candidates.json")
            if candidates is not None and index < len(candidates):
                task["candidate_id"] = candidates[index]["id"]
                if task["trajectory_index"] is not None:
                    slots = load(f"lineage/candidates/{task['candidate_id']}/slots.json")
                    if slots is not None:
                        slot = slots[task["trajectory_index"]]
                        task["native_support_kind"] = "main"
                        native_outcome = f"lineage/candidates/{task['candidate_id']}/simulations/{task['trajectory_index']:03}/outcome.json"
        elif node in {"perspective_screen_native", "perspective_final_native"}:
            stage = "screen" if "screen" in node else "final_validation"
            slots = load(f"perspective/{stage}/slots.json")
            if slots is not None and task["index"] < len(slots):
                slot = slots[task["index"]]
                task["candidate_id"] = slot["candidate_id"]
                task["native_support_kind"] = slot["kind"]
                native_outcome = f"perspective/{stage}/cases/{task['candidate_id']}/{task['index']:05}/outcome.json"
        elif node == "perspective_bounded_refinement" and load("perspective/refinement_tasks.json") is not None:
            manifest = load("perspective/refinement_tasks.json")
            slots_by_index = cache.setdefault("refinement_slots_by_index", {slot["index"]: slot for slot in manifest})
            if task["index"] not in slots_by_index:
                ledger_path = "scheduler/dynamic_counts/" + node + ".json"
                ledger = load(ledger_path)
                if (ledger is not None and ledger.get("node") == node
                        and ledger.get("reason") == "unused_reserved_quota_after_manifest_preparation"
                        and type(ledger.get("active_tasks")) is int and type(ledger.get("reserved_tasks")) is int
                        and 0 <= ledger["active_tasks"] <= task["index"] < ledger["reserved_tasks"]
                        and ledger["reserved_tasks"] == task["node_reserved_tasks"]
                        and ledger.get("unused_tasks") == ledger["reserved_tasks"] - ledger["active_tasks"]
                        and task["state"] == "CANCELLED" and task.get("start") is None
                        and not any(task.get(field, 0) for field in ["cpu_seconds", "duration_seconds", "elapsed_seconds", "cpus", "worker_cpu_seconds"])):
                    task.update(unused_reserved_quota=True, quota_ledger_source=ledger_path)
                    task.pop("candidate_id", None)
                    task.pop("refinement_attempt_directory", None)
                    continue
                raise ValueError("Refinement worker lacks a frozen source slot: " + task["key"])
            attempt = slots_by_index[task["index"]]
            if task.get("source_candidate_index", attempt["source_index"]) != attempt["source_index"]:
                raise ValueError("Refinement source index disagrees with the scheduler manifest")
            task.update(candidate_id=attempt["source_id"], source_candidate_index=attempt["source_index"],
                        refinement_replicate=attempt["replicate"], refinement_attempt_directory=attempt["attempt_directory"])
        else:
            if (node == "perspective_bounded_refinement" and "source_candidate_index" in task
                    and task.get("start") is not None):
                raise ValueError("Started replicated refinement lacks its frozen refinement_tasks.json")
            candidate_path = {
                "perspective_search": "perspective/candidates.json",
                "perspective_bounded_refinement": "perspective/screen_candidates.json",
                "perspective_screen_diagnostics": "perspective/screen/candidates.json",
                "perspective_final_diagnostics": "perspective/final_validation/candidates.json",
            }.get(node)
            candidates = load(candidate_path) if candidate_path else None
            if candidates is not None and index < len(candidates):
                task["candidate_id"] = candidates[index]["id"]
        if slot is not None:
            for field in ["episode_id", "oxygen", "replicate", "seed", "founding_group", "group", "harvest_time_days"]:
                if field in slot:
                    task[field] = slot[field]
            task["observation_rows"] = len(slot.get("indices", slot.get("observation_rows", [])))
        if native_outcome and task["state"] in TERMINAL:
            outcome = load(native_outcome)
            task["native_outcome"] = outcome.get("status") if outcome else "not_recorded"


def attach_worker_usage(run, tasks):
    by_job = collections.defaultdict(list)
    for path in sorted((run / "accounting").glob("*.json")):
        value = read_json(path)
        by_job[str(value.get("SLURM_JOB_ID"))].append((path, value))
    for task in tasks:
        entries = by_job.get(task.get("raw_job_id"), [])
        if len(entries) > 1:
            raise ValueError("Multiple worker attempts share a scheduler task; explicit attempt accounting is required: " + task["key"])
        if entries:
            if task.get("unused_reserved_quota"):
                raise ValueError("Unused reserved slot has a worker execution record: " + task["key"])
            path, value = entries[0]
            task.update({"worker_cpu_seconds": value["self_cpu_seconds"] + value["child_cpu_seconds"],
                         "worker_elapsed_seconds": value["elapsed_seconds"],
                         "worker_status": value["status"], "worker_usage_source": str(path.relative_to(run))})


def scientific_status(run, tasks):
    """Read scientific completion explicitly; task termination does not imply it."""
    preparation = next((task for task in tasks if task["node"] == "perspective_prepare"), {})
    searches = [task for task in tasks if task["node"] == "perspective_search" and task.get("start") is not None]
    blocked = preparation.get("state") == "FAILED" and not searches
    results_path = run / "report/results.json"
    results = read_json(results_path) if results_path.exists() else {}
    if results.get("run_id", run.name) != run.name:
        raise ValueError("Scientific report belongs to another run")
    complete = results.get("complete_scientific_baseline")
    if complete is not None and type(complete) is not bool:
        raise ValueError("Scientific completion must be an explicit boolean")
    if blocked:
        if complete:
            raise ValueError("Scientific report claims completion after failed perspective preparation")
        complete = False
    known_calls, missing_counters = 0, 0
    for task in searches:
        candidate = task.get("candidate_id")
        path = run / "perspective/candidates" / str(candidate) / "checkpoint.json.status.json"
        if candidate and path.exists():
            value = read_json(path).get("evaluations")
            if type(value) is int and value >= 0:
                known_calls += value
                continue
        missing_counters += 1
    native_workers = sum(task["node"] in {"perspective_screen_native", "perspective_final_native"}
                         and task.get("start") is not None for task in tasks)
    acceptance = results.get("perspective", {}).get("acceptance", {})
    return {"scientific_campaign_complete": complete,
            "scientific_workflow_status": ("stopped_before_perspective_fitting" if blocked else
                                           "complete" if complete is True else "not_complete" if complete is False else
                                           "not_evaluated_by_accounting"),
            "scientific_status_source": "report/results.json" if results_path.exists() else None,
            "scientific_acceptance_decision": acceptance.get("decision"),
            "scientific_validation_status": acceptance.get("validation_status"),
            "perspective_search_workers_started": len(searches),
            "perspective_optimizer_started": True if known_calls else None if missing_counters else False,
            "perspective_recorded_optimizer_calls": known_calls,
            "perspective_started_searches_without_counters": missing_counters,
            "perspective_native_workers_started": native_workers,
            # A scheduler-started worker can fail a guard before launching an
            # engine. Only a zero worker count establishes zero native calls.
            "perspective_native_simulations_started": 0 if not native_workers else None}


def export_objectives(run, out, all_tasks):
    calls = []
    refinement_paths = set()
    for task in all_tasks:
        if task.get("unused_reserved_quota"):
            calls.append({"phase": task["phase"], "job_id": task["key"], "candidate_id": None,
                          "source_candidate_index": task.get("source_candidate_index"),
                          "refinement_replicate": task.get("refinement_replicate"), "attempt_directory": None,
                          "objective_calls": 0, "state": task["state"],
                          "call_count_source": task["quota_ledger_source"], "count_status": "unused_reserved_quota"})
            continue
        candidate = task.get("candidate_id")
        if not candidate:
            continue
        phase = task["phase"]
        final = None
        if phase.endswith(".fit"):
            path = run / "lineage/candidates" / candidate / "checkpoint.json.status.json"
        elif phase == "perspective_search":
            path = run / "perspective/candidates" / candidate / "checkpoint.json.status.json"
        elif phase == "perspective_bounded_refinement":
            directory = ((run / "perspective" / task["refinement_attempt_directory"]).resolve()
                         if task.get("refinement_attempt_directory") else run / "perspective/refinement" / candidate)
            if not directory.resolve().is_relative_to((run / "perspective").resolve()):
                raise ValueError("Refinement attempt directory escapes the frozen run")
            if directory.resolve() in refinement_paths:
                raise ValueError("Multiple refinement slots share one objective-counter directory")
            refinement_paths.add(directory.resolve())
            path = directory / "final.json"
            if not path.exists():
                path = path.with_name("outcome.json")
        else:
            continue
        if path.exists():
            final = read_json(path)
        count = final.get("evaluations") if final else None
        calls.append({"phase": phase, "job_id": task["key"], "candidate_id": candidate,
                      "source_candidate_index": task.get("source_candidate_index"),
                      "refinement_replicate": task.get("refinement_replicate"),
                      "attempt_directory": task.get("refinement_attempt_directory"),
                      "objective_calls": count, "state": task["state"],
                      "call_count_source": str(path.relative_to(run)) if path.exists() else None,
                      "count_status": "recorded" if count is not None else final.get("status", "not_recorded") if final else "not_recorded"})
    write_csv(out / "objective_calls.csv", calls,
              ["phase", "job_id", "candidate_id", "source_candidate_index", "refinement_replicate", "attempt_directory",
               "objective_calls", "state", "call_count_source", "count_status"])
    grouped = collections.defaultdict(list)
    for task in all_tasks:
        if task.get("native_support_kind"):
            grouped[(task["phase"], task["candidate_id"], task["native_support_kind"])].append(task)
    native = []
    for (phase, candidate, kind), members in grouped.items():
        native.append({"phase": phase, "candidate_id": candidate, "support_kind": kind,
                       "expected_tasks": len(members),
                       "terminal_tasks": sum(t["state"] in TERMINAL for t in members),
                       "completed_tasks": sum(t["state"] == "COMPLETED" for t in members),
                       "complete_simulation_tasks": sum(t.get("native_outcome") == "complete" for t in members),
                       "cpu_hours": sum(t.get("cpu_seconds", 0.) for t in members if t["state"] in TERMINAL) / 3600.,
                       "unique_episodes": len({t["episode_id"] for t in members if "episode_id" in t}),
                       "replicates": len({t["replicate"] for t in members if "replicate" in t}),
                       "observation_rows_across_replicates": sum(t.get("observation_rows", 0) for t in members),
                       "job_ids": ",".join(t["key"] for t in members)})
    write_csv(out / "native_objectives.csv", native,
              ["phase", "candidate_id", "support_kind", "expected_tasks", "terminal_tasks", "completed_tasks", "complete_simulation_tasks", "cpu_hours",
               "unique_episodes", "replicates", "observation_rows_across_replicates", "job_ids"])


def make_graph(tasks, plan, node_keys):
    by_key = {t["key"]: t for t in tasks}
    complete = {key for key, t in by_key.items() if t["state"] in TERMINAL}
    graph = {}
    for rank, node in enumerate(plan["nodes"]):
        members = [k for k in node_keys[node["name"]] if k in complete]
        if not members:
            continue
        upstream = "barrier:" + node["depends_on"] if node.get("depends_on") else None
        # Late controller submission is an intrinsic orchestration delay, not a
        # resource queue delay. Normal pre-submitted DAG nodes have zero delay.
        upstream_end = max((by_key[k].get("end") or 0 for k in node_keys.get(node.get("depends_on"), []) if k in complete), default=0.)
        for key in members:
            task = by_key[key]
            deps = [upstream] if upstream else []
            for parent_index in task.get("parent_indices", [task["parent_index"]] if task.get("parent_index") is not None else []):
                parent = str(key.split("_")[0]) + "_" + str(parent_index)
                if parent not in complete:
                    raise ValueError("Completed child lacks terminal parent: " + key)
                deps.append(parent)
            delay = max(0., (task.get("submit") or 0.) - upstream_end) if upstream_end else 0.
            graph[key] = {
                "duration": task.get("duration_seconds", 0.), "cpus": task.get("cpus", 0),
                "dependencies": list(dict.fromkeys(deps)), "release_delay": delay,
                # Preserve observed dispatch order, without sorting by duration.
                "priority": (rank, task.get("start") if task.get("start") is not None else math.inf, task["index"]),
            }
        graph["barrier:" + node["name"]] = {
            "duration": 0., "cpus": 0, "dependencies": members,
            "release_delay": 0., "priority": (rank, math.inf, math.inf),
        }
    for key, value in graph.items():
        for dependency in value["dependencies"]:
            if dependency not in graph:
                raise ValueError("Task graph has an unavailable predecessor: " + key + " -> " + dependency)
    return graph


def replay(graph, cap):
    """Event-driven, nonpreemptive list schedule; no hindsight duration priority."""
    children = collections.defaultdict(list)
    missing = {}
    dependency_end = collections.defaultdict(float)
    for key, task in graph.items():
        missing[key] = len(task["dependencies"])
        if task["cpus"] > cap:
            raise ValueError("Task exceeds the original campaign CPU cap: " + key)
        for dep in task["dependencies"]:
            children[dep].append(key)
    releases, ready, running = [], [], []
    for key, count in missing.items():
        if not count:
            heapq.heappush(releases, (graph[key]["release_delay"], graph[key]["priority"], key))
    used = 0
    now = 0.
    result = {}
    while len(result) < len(graph) or running:
        while running and running[0][0] <= now + 1e-9:
            end, key = heapq.heappop(running)
            used -= graph[key]["cpus"]
            for child in children[key]:
                missing[child] -= 1
                dependency_end[child] = max(dependency_end[child], end)
                if not missing[child]:
                    release = dependency_end[child] + graph[child]["release_delay"]
                    heapq.heappush(releases, (release, graph[child]["priority"], child))
        while releases and releases[0][0] <= now + 1e-9:
            _, priority, key = heapq.heappop(releases)
            heapq.heappush(ready, (priority, key))
        started = False
        deferred = []
        while ready:
            priority, key = heapq.heappop(ready)
            task = graph[key]
            if used + task["cpus"] > cap:
                deferred.append((priority, key))
                continue
            end = now + task["duration"]
            result[key] = (now, end)
            used += task["cpus"]
            heapq.heappush(running, (end, key))
            started = True
        for item in deferred:
            heapq.heappush(ready, item)
        if started and running and running[0][0] <= now + 1e-9:
            continue
        next_times = ([running[0][0]] if running else []) + ([releases[0][0]] if releases else [])
        if not next_times:
            if len(result) != len(graph):
                raise ValueError("Cycle or unschedulable task graph")
            break
        now = min(next_times)
    return result


def curve(tasks, times):
    events = collections.defaultdict(lambda: collections.defaultdict(float))
    zero_duration_cpu = 0.
    for task in tasks:
        if task["key"] not in times:
            continue
        start, end = times[task["key"]]
        if end <= start:
            zero_duration_cpu += task.get("cpu_seconds", 0.)
            continue
        rate = task.get("cpu_seconds", 0.) / (end - start)
        events[start][task["category"]] += rate
        events[end][task["category"]] -= rate
        events[start]["concurrent_task_cpus"] += task.get("cpus", 0)
        events[end]["concurrent_task_cpus"] -= task.get("cpus", 0)
    names = [name for name, _ in CATEGORIES]
    current = collections.defaultdict(float)
    rows = []
    for instant, changes in sorted(events.items()):
        for name, delta in changes.items():
            current[name] += delta
        rows.append({"time_seconds": instant, **{name: max(0., current[name]) for name in names},
                     "estimated_busy_cpus": sum(max(0., current[name]) for name in names),
                     "concurrent_task_cpus": max(0., current["concurrent_task_cpus"])})
    return rows, zero_duration_cpu


def integrate(rows, column):
    return sum((b["time_seconds"] - a["time_seconds"]) * a[column] for a, b in zip(rows, rows[1:]))


def render(out, summary, actual_rows, adjusted_rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    import numpy as np

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42, "svg.fonttype": "none"})
    fig, axes = plt.subplots(2, 1, figsize=(12, 7.2))
    fig.subplots_adjust(left=.075, right=.985, bottom=.09, top=.79, hspace=.43)
    for axis, rows, mode, label in zip(axes, [actual_rows, adjusted_rows], ["actual", "adjusted"],
                                     ["Observed schedule", "Scheduler-adjusted replay"]):
        x = np.array([r["time_seconds"] for r in rows]) / 60.
        values = np.array([[r[name] for r in rows] for name, _ in CATEGORIES])
        axis.stackplot(x, values, colors=[color for _, color in CATEGORIES], step="post", linewidth=0, alpha=.95)
        axis.step(x, [r["concurrent_task_cpus"] for r in rows], where="post", color="#292929", linewidth=.8)
        axis.axhline(summary["cpu_cap"], color="#5e5e5e", linewidth=.8, linestyle="--")
        axis.set_ylim(0, summary["cpu_cap"] * 1.08)
        axis.set_xlim(0, max(x[-1], 1/60))
        if summary["cpu_cap"] == 1000:
            axis.set_yticks([0, 250, 500, 750, 1000])
        axis.set_ylabel("CPU utilization (cores)")
        axis.set_xlabel("Elapsed time (minutes)")
        elapsed = summary[mode + "_elapsed_seconds"] / 60
        occupancy = 100 * summary[mode + "_busy_capacity_fraction"]
        axis.set_title(f"{label}: {elapsed:.1f} min; average busy CPU {occupancy:.1f}% of capacity", loc="left", fontsize=11)
        axis.grid(axis="y", color="#dddddd", linewidth=.5, zorder=0)
        axis.set_axisbelow(True)
    active_categories = {name for name, _ in CATEGORIES if any(row[name] > 1e-8 for row in actual_rows)}
    handles = [Patch(facecolor=color, label=name) for name, color in CATEGORIES if name in active_categories]
    handles += [Line2D([], [], color="#292929", linewidth=.9, label="Concurrent task CPUs"),
                Line2D([], [], color="#5e5e5e", linewidth=.8, linestyle="--", label=f"{summary['cpu_cap']:,}-CPU capacity")]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, .94), ncol=3, frameon=False, fontsize=9)
    heading = "Stopped before perspective fitting" if summary["scientific_workflow_status"] == "stopped_before_perspective_fitting" else "Fresh baseline fitting"
    fig.suptitle(f"{heading}: {summary['measured_cpu_hours']:.2f} measured CPU-hours" +
                 (" — incomplete campaign" if not summary["complete"] else ""), fontsize=13, y=.99)
    fig.text(.5, .012, "Colored area estimates busy CPU from each task's total CPU time / elapsed time; it is not instantaneous CPU sampling.", ha="center", fontsize=9, color="#444444")
    for extension in ["png", "pdf", "svg"]:
        fig.savefig(out / ("cpu_utilization." + extension), dpi=180)
    plt.close(fig)


def write_report(out, summary):
    total = summary["measured_cpu_hours"] + summary["ancillary_preflight_cpu_hours"]
    stopped = summary["scientific_workflow_status"] == "stopped_before_perspective_fitting"
    qualification = summary.get("lineage_native_finite_qualification")
    qualification_text = (
        f"The saved finite-support audit distinguishes {qualification['finite_complete']:,} finite complete-status attempts, "
        f"{qualification['nonfinite_complete']:,} complete-status attempts with nonfinite observations, and "
        f"{qualification['engine_failed']:,} failed attempts. " if qualification else
        "A complete wrapper status does not establish finite observation support. ")
    lines = ["# CPU utilization for the scratch attempt", "",
             ("The attempt stopped before perspective fitting. No perspective optimization or validation simulation ran. "
              "The two-baseline scientific workflow is incomplete."
              if stopped else "The saved scientific report marks the baseline complete. This report independently accounts for realized tasks."
              if summary["scientific_campaign_complete"] is True else
              "The saved scientific report marks the baseline incomplete. Accounting completeness is a separate result."
              if summary["scientific_campaign_complete"] is False else
              "This report accounts for realized tasks; accounting completeness alone does not establish scientific completion."), "",
             f"Measured campaign CPU use was {summary['measured_cpu_hours']:.6f} CPU-hours. The separate runtime-transfer preflight consumed "
             f"{summary['ancillary_preflight_cpu_hours']:.6f} CPU-hours, giving {total:.6f} CPU-hours including preflight.", "",
             f"| Timing view | Elapsed minutes | Mean busy cores | Mean share of {summary['cpu_cap']:,}-CPU capacity |",
             "| --- | ---: | ---: | ---: |"]
    for mode, label in [("actual", "Observed"), ("adjusted", "Scheduler-adjusted replay")]:
        fraction = summary[mode + "_busy_capacity_fraction"]
        lines.append(f"| {label} | {summary[mode + '_elapsed_seconds'] / 60:.2f} | {fraction * summary['cpu_cap']:.2f} | {100 * fraction:.2f}% |")
    lines += ["", f"The replay removes {summary['scheduler_adjustment_seconds']:.0f} seconds of scheduler waiting/polling while retaining "
              "the realized tasks, phase barriers, streamed candidate dependencies, measured task durations and long tails. The original cap "
              f"remains {summary['cpu_cap']:,} CPUs. Observed/replayed peaks are "
              f"{summary['actual_peak_concurrent_task_cpus']:,.0f}/{summary['adjusted_peak_concurrent_task_cpus']:,.0f} concurrent "
              "assigned task CPUs; instantaneous busy CPU was not sampled.", "",
              "| Logical task slots | Count |", "| --- | ---: |"]
    lines += [f"| {state} | {count:,} |" for state, count in summary["task_states"].items()]
    lines += [f"| Total | {summary['tasks']:,} |", "",
              f"There are {summary['never_started_tasks']:,} never-started slots. "
              f"Worker resource records cover {summary['tasks_with_worker_usage']:,} of {summary['started_tasks']:,} started attempts. Native wrapper outcome statuses are recorded "
              f"separately from scheduler statuses: {summary['lineage_native_outcomes'].get('complete', 0):,} complete-status "
              f"and {summary['lineage_native_outcomes'].get('failed', 0):,} failed-status outcomes across "
              f"{sum(summary['lineage_native_outcomes'].values()):,} lineage attempts. " + qualification_text +
              "Failed and nonfinite work costs remain included. " +
              ("The downstream failed analysis/eligibility workers did not execute perspective searches or simulations." if stopped else
               "Scientific completion is taken from the saved scientific report, separately from scheduler states."), "",
              f"Worker self plus completed-child CPU totals {summary['worker_cpu_hours_crosscheck']:.6f} CPU-hours. "
              "Official scheduler CPU totals additionally cover interpreter/dispatcher startup. " +
              ("The terminal report job's final cost is included in this independent post-completion collection." if summary["accounting_complete"] else
               "This partial accounting snapshot excludes nonterminal tasks."), "",
              "[CPU figure](cpu_utilization.png) · [PDF](cpu_utilization.pdf) · " +
              ("[method](METHOD.md) · " if (out / "METHOD.md").exists() else "") + "[summary](summary.json) · "
              "[task accounting](tasks.csv) · [phase costs](phases.csv) · [coverage](coverage.json)", "",
              "Colored busy-core curves spread each task's measured CPU time uniformly across its elapsed interval. They estimate temporal "
              "CPU use; they are not instantaneous CPU samples. Scheduler adjustment does not invent unrun perspective work or claim a completed scientific baseline.", ""]
    (out / "CPU_REPORT.md").write_text("\n".join(lines))


def self_test():
    graph = {
        "a": {"duration": 5., "cpus": 1, "dependencies": [], "release_delay": 0., "priority": (0, 0, 0)},
        "b": {"duration": 2., "cpus": 1, "dependencies": [], "release_delay": 0., "priority": (0, 0, 1)},
        "c": {"duration": 3., "cpus": 1, "dependencies": ["b"], "release_delay": 0., "priority": (0, 1, 2)},
        "barrier": {"duration": 0., "cpus": 0, "dependencies": ["a", "c"], "release_delay": 0., "priority": (1, 0, 0)},
        "d": {"duration": 4., "cpus": 1, "dependencies": ["barrier"], "release_delay": 2., "priority": (1, 0, 1)},
    }
    result = replay(graph, 2)
    assert result == {"a": (0., 5.), "b": (0., 2.), "c": (2., 5.), "barrier": (5., 5.), "d": (7., 11.)}, result
    serial = replay(graph, 1)
    assert serial["c"][0] >= serial["b"][1]
    assert serial["d"][0] == max(serial["a"][1], serial["c"][1]) + 2
    tasks = [{"key": k, "category": "Lineage search", "cpus": graph[k]["cpus"], "cpu_seconds": graph[k]["duration"] * .5} for k in ["a", "b", "c", "d"]]
    rows, zero = curve(tasks, result)
    assert abs(integrate(rows, "estimated_busy_cpus") - 7) < 1e-9
    assert max(row["concurrent_task_cpus"] for row in rows) == 2
    assert zero == 0
    exclusions = collections.Counter()
    collapsed = {"JobID": "123_[0-2,4%1000]", "JobIDRaw": "123", "State": "CANCELLED", "AllocCPUS": "0", "ElapsedRaw": "0", "TotalCPU": "00:00:00"}
    expanded = list(expanded_rows([collapsed], exclusions))
    assert [row["JobID"] for row in expanded] == ["123_0", "123_1", "123_2", "123_4"]
    assert all(row["JobIDRaw"] == "" for row in expanded)
    try:
        list(expanded_rows([dict(collapsed, TotalCPU="00:00:01")], exclusions))
        raise AssertionError("Nonzero range CPU was multiplied")
    except ValueError:
        pass
    sparse_fixture_test()
    print("Replay checks passed: legacy/sparse slots, multi-parent scores, source/replicate counters, scientific status, CPU cap/conservation and terminal-array expansion.")


def sparse_fixture_test():
    """Exercise parsing/accounting with only synthetic saved files, no scheduler."""
    groups = [
        {"first": 0, "last": 0, "phase": "fit", "candidate": 0, "parent": None},
        {"first": 1, "last": 1, "phase": "fit", "candidate": 1, "parent": None},
        {"first": 2, "last": 2, "phase": "finalize", "candidate": 0, "parent": 0},
        {"first": 3, "last": 3, "phase": "finalize", "candidate": 1, "parent": 1},
        {"first": 6, "last": 8, "indices": [6, 8], "trajectory_indices": [1, 0], "phase": "simulate", "candidate": 0, "parent": 2},
        {"first": 7, "last": 9, "indices": [7, 9], "trajectory_indices": [0, 1], "phase": "simulate", "candidate": 1, "parent": 3},
        {"first": 4, "last": 4, "phase": "score", "candidate": 0, "parent": None, "parents": [6, 8]},
        {"first": 5, "last": 5, "phase": "score", "candidate": 1, "parent": None, "parents": [7, 9]},
    ]
    stream = {"name": "lineage_shared_stream", "kind": "stream", "tasks": 10, "depends_on": None,
              "manifest_value": {"task_groups": groups}}
    contexts = task_contexts(stream)
    assert contexts[7]["candidate_index"] == 1
    assert contexts[6]["trajectory_index"] == 1 and contexts[8]["trajectory_index"] == 0
    assert contexts[4]["parent_indices"] == [6, 8]
    legacy = {"name": "legacy", "kind": "command", "tasks": 3,
              "manifest_value": {"task_groups": [{"first": 0, "last": 2, "phase": "command", "candidate": None, "parent": None}]}}
    assert [value["candidate_index"] for value in task_contexts(legacy).values()] == [0, 1, 2]
    for mutation in ["overlap", "missing", "trajectory_length"]:
        bad = json.loads(json.dumps(stream))
        target = bad["manifest_value"]["task_groups"][4]
        if mutation == "overlap":
            target["indices"] = [6, 7]
        elif mutation == "missing":
            target["indices"] = [6]
            target["trajectory_indices"] = [1]
        else:
            target["trajectory_indices"] = [1]
        try:
            task_contexts(bad)
            raise AssertionError("Invalid sparse groups accepted: " + mutation)
        except ValueError:
            pass
    with tempfile.TemporaryDirectory(prefix="baseline_cpu_fixture_") as directory:
        run = Path(directory)
        (run / "scheduler").mkdir()
        (run / "perspective").mkdir()
        (run / "report").mkdir()
        refinement = {"name": "perspective_bounded_refinement", "kind": "command", "tasks": 4,
                      "depends_on": "lineage_shared_stream", "manifest_value": {"task_groups": [
                          {"first": 0, "last": 1, "phase": "command", "candidate": None, "parent": None, "source_candidate_index": 0},
                          {"first": 2, "last": 3, "phase": "command", "candidate": None, "parent": None, "source_candidate_index": 1}]}}
        report = {"name": "report_accept_for_now", "kind": "command", "tasks": 1,
                  "depends_on": "perspective_bounded_refinement", "manifest_value": {"task_groups": [
                      {"first": 0, "last": 0, "phase": "command", "candidate": None, "parent": None}]}}
        plan = {"nodes": [stream, refinement, report]}
        write_json(run / "scheduler/plan.json", plan)
        write_json(run / "scheduler/jobs.json", {stream["name"]: "1000", refinement["name"]: "2000", report["name"]: "3000"})
        slots = [{"index": index, "source_index": index // 2, "source_id": "source_" + str(index // 2),
                  "replicate": index % 2, "attempt_directory": f"refinement/source_{index // 2}/replicate_{index % 2:03}"}
                 for index in range(4)]
        write_json(run / "perspective/refinement_tasks.json", slots)
        for slot, count in zip(slots, [2, 3, 5, 7]):
            attempt = run / "perspective" / slot["attempt_directory"]
            attempt.mkdir(parents=True)
            write_json(attempt / "final.json", {"evaluations": count})
        times = [(0, 2), (0, 5), (2, 3), (5, 6), (7, 8), (9, 10), (3, 7), (6, 9), (3, 5), (6, 7)]
        entries = [(f"1000_{index}", start, end) for index, (start, end) in enumerate(times)]
        entries += [(f"2000_{index}", 10 if index < 3 else 12, 12 if index < 3 else 14) for index in range(4)]
        entries.append(("3000", 14, 15))
        raw = run / "accounting.psv"
        with raw.open("w", newline="") as output:
            fields = ["JobID", "JobIDRaw", "State", "AllocCPUS", "ElapsedRaw", "TotalCPU", "Submit", "Eligible", "Start", "End", "ExitCode"]
            writer = csv.DictWriter(output, fieldnames=fields, delimiter="|")
            writer.writeheader()
            for key, start, end in entries:
                iso = lambda seconds: f"2026-01-01T00:00:{seconds:02}"
                writer.writerow({"JobID": key, "JobIDRaw": key, "State": "COMPLETED", "AllocCPUS": 1,
                                 "ElapsedRaw": end - start, "TotalCPU": f"00:00:{(end-start)*.5:06.3f}",
                                 "Submit": iso(0), "Eligible": iso(start), "Start": iso(start), "End": iso(end), "ExitCode": "0:0"})
        tasks, saved_plan, node_keys, coverage = normalize(run, raw, set())
        assert coverage["expected_tasks"] == coverage["accounted_task_rows"] == 15
        assert not coverage["nonterminal_tasks"] and not coverage["unmapped_job_ids"]
        graph = make_graph(tasks, saved_plan, node_keys)
        assert set(graph["1000_4"]["dependencies"]) == {"1000_6", "1000_8"}
        adjusted = replay(graph, 2)
        assert adjusted["1000_4"][0] >= max(adjusted[key][1] for key in ["1000_6", "1000_8"])
        assert adjusted["2000_0"][0] >= max(adjusted[key][1] for key in ["1000_4", "1000_5"])
        actual = {task["key"]: (task["start"] - tasks[0]["start"], task["end"] - tasks[0]["start"]) for task in tasks}
        for timing in [actual, adjusted]:
            rows, zero = curve(tasks, timing)
            assert abs(integrate(rows, "estimated_busy_cpus") + zero - sum(task["cpu_seconds"] for task in tasks)) < 1e-9
        rows, _ = curve(tasks, adjusted)
        assert max(row["concurrent_task_cpus"] for row in rows) <= 2
        enrich_tasks(run, tasks)
        export_objectives(run, run / "report", tasks)
        calls = list(csv.DictReader((run / "report/objective_calls.csv").open()))
        assert len(calls) == 4 and sum(int(row["objective_calls"]) for row in calls) == 17
        assert len({row["call_count_source"] for row in calls}) == 4
        assert {row["refinement_replicate"] for row in calls} == {"0", "1"}
        write_json(run / "report/results.json", {"run_id": run.name, "complete_scientific_baseline": False})
        assert scientific_status(run, tasks)["scientific_campaign_complete"] is False
        write_json(run / "report/results.json", {"run_id": run.name, "complete_scientific_baseline": True})
        assert scientific_status(run, tasks)["scientific_campaign_complete"] is True
        slots[1]["attempt_directory"] = slots[0]["attempt_directory"]
        write_json(run / "perspective/refinement_tasks.json", slots)
        enrich_tasks(run, tasks)
        try:
            export_objectives(run, run / "report", tasks)
            raise AssertionError("Shared multistart counter directory was counted repeatedly")
        except ValueError:
            pass
        slots[1]["attempt_directory"] = "refinement/source_0/replicate_001"
        write_json(run / "perspective/refinement_tasks.json", slots[:2])
        (run / "scheduler/dynamic_counts").mkdir()
        write_json(run / "scheduler/dynamic_counts/perspective_bounded_refinement.json",
                   {"node": "perspective_bounded_refinement", "active_tasks": 2, "reserved_tasks": 4,
                    "unused_tasks": 2, "reason": "unused_reserved_quota_after_manifest_preparation"})
        unused = [task for task in tasks if task["node"] == "perspective_bounded_refinement" and task["index"] >= 2]
        for task in unused:
            task.update(state="CANCELLED", start=None, cpus=0, cpu_seconds=0., duration_seconds=0., elapsed_seconds=0.)
        enrich_tasks(run, tasks)
        assert all(task.get("unused_reserved_quota") and "refinement_attempt_directory" not in task for task in unused)
        export_objectives(run, run / "report", tasks)
        calls = list(csv.DictReader((run / "report/objective_calls.csv").open()))
        zero_calls = [row for row in calls if row["count_status"] == "unused_reserved_quota"]
        assert len(zero_calls) == 2 and all(row["objective_calls"] == "0" and not row["attempt_directory"] for row in zero_calls)
        unused[0].update(state="FAILED", start=0., cpus=1, cpu_seconds=.1)
        try:
            enrich_tasks(run, tasks)
            raise AssertionError("Started/metered missing source slot was classified as unused quota")
        except ValueError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, help="Frozen run directory; required except with --self-test")
    parser.add_argument("--output", type=Path, help="Output directory; defaults to RUN/report/cpu_utilization")
    parser.add_argument("--accounting-input", type=Path, help="Saved UTC sacct export; defaults to RUN/report/cpu_utilization/slurm_accounting_utc.psv")
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--ancillary-job", action="append", default=[], help="Additional preflight job ID; otherwise reuse saved collection metadata")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.run is None:
        parser.error("--run is required except with --self-test")
    run = args.run.resolve()
    saved = run / "report/cpu_utilization"
    out = args.output.resolve() if args.output else saved
    out.mkdir(parents=True, exist_ok=True)
    ancillary_jobs = args.ancillary_job
    if not ancillary_jobs and (saved / "collection.json").exists():
        ancillary_jobs = read_json(saved / "collection.json").get("ancillary_jobs", [])
    if args.collect:
        collect(run, out, ancillary_jobs)
    raw = args.accounting_input.resolve() if args.accounting_input else (out if args.collect else saved) / "slurm_accounting_utc.psv"
    tasks, plan, node_keys, coverage = normalize(run, raw, set(ancillary_jobs))
    write_json(out / "coverage.json", coverage)
    if coverage["unmapped_job_ids"]:
        raise ValueError("Unattributed task rows: " + str(coverage["unmapped_job_ids"]))
    if coverage["nonterminal_tasks"] and not args.allow_partial:
        raise ValueError("Campaign incomplete; final reporting waits for every task. Use --allow-partial only for an explicit interim view.")
    enrich_tasks(run, tasks)
    attach_worker_usage(run, tasks)
    export_objectives(run, out, tasks)
    scientific = scientific_status(run, tasks)
    blocked = scientific["scientific_workflow_status"] == "stopped_before_perspective_fitting"
    if blocked:
        # These descendants may have executed only imports/error reporting after
        # the failed prerequisite. Their scheduler phase names are not proof that
        # an optimizer or validation simulation actually ran.
        for task in tasks:
            if task["node"].startswith("perspective_"):
                task["category"] = "Preparation, analysis and report"
    tasks = [t for t in tasks if t["state"] in TERMINAL]
    if not any(t.get("start") is not None for t in tasks):
        raise ValueError("No completed execution intervals yet")
    graph = make_graph(tasks, plan, node_keys)
    cap = read_json(run / "scheduler/specification.json")["max_cpus"]
    adjusted = replay(graph, cap)
    start = min(t["start"] for t in tasks if t.get("start") is not None)
    actual = {t["key"]: (t["start"] - start, t["start"] - start + t["duration_seconds"]) for t in tasks if t.get("start") is not None}
    actual_rows, zero_actual = curve(tasks, actual)
    adjusted_rows, zero_adjusted = curve(tasks, adjusted)
    cpu_seconds = sum(t.get("cpu_seconds", 0.) for t in tasks)
    summary = {
        "complete": not coverage["nonterminal_tasks"], "run_id": run.name, "cpu_cap": cap,
        "accounting_complete": not coverage["nonterminal_tasks"],
        **scientific,
        "never_started_tasks": sum(t.get("start") is None for t in tasks),
        "started_tasks": sum(t.get("start") is not None for t in tasks),
        "unused_refinement_reserved_quota_tasks": sum(bool(t.get("unused_reserved_quota")) for t in tasks),
        "tasks": len(tasks), "task_states": dict(collections.Counter(t["state"] for t in tasks)),
        "actual_start_utc": dt.datetime.fromtimestamp(start, dt.timezone.utc).isoformat(),
        "actual_elapsed_seconds": max(end for _, end in actual.values()),
        "adjusted_elapsed_seconds": max(end for key, (_, end) in adjusted.items()),
        "measured_cpu_hours": cpu_seconds / 3600.,
        "worker_cpu_hours_crosscheck": sum(t.get("worker_cpu_seconds", 0.) for t in tasks) / 3600.,
        "tasks_with_worker_usage": sum("worker_cpu_seconds" in t for t in tasks),
        "lineage_native_outcomes": dict(collections.Counter(t["native_outcome"] for t in tasks if t["phase"].endswith(".simulate") and "native_outcome" in t)),
        "zero_duration_cpu_seconds_not_drawn": zero_actual,
        "ancillary_preflight_cpu_hours": sum(seconds(r["TotalCPU"]) for r in coverage["ancillary_rows"]) / 3600.,
        "raw_input_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
        "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "adjustment": "Realized-work DAG replay, original CPU cap, observed task durations and dispatch order; no resource queue or scheduler dependency-polling delays; preserve late controller submission, scientific barriers and outcomes.",
    }
    qualification_path = run / "report/stopped_run_evidence.json"
    if qualification_path.exists():
        evidence = read_json(qualification_path).get("lineage", {})
        counts = [value.get("native_outcome_counts", {}) for value in evidence.values()]
        if counts and all("complete_finite" in count and "complete_nonfinite" in count for count in counts):
            qualification = {"finite_complete": sum(count["complete_finite"] for count in counts),
                             "nonfinite_complete": sum(count["complete_nonfinite"] for count in counts),
                             "engine_failed": sum(count.get("failed", 0) for count in counts),
                             "source": str(qualification_path.relative_to(run))}
            if qualification["finite_complete"] + qualification["nonfinite_complete"] != summary["lineage_native_outcomes"].get("complete", 0):
                raise ValueError("Saved finite-support audit disagrees with native wrapper outcome counts")
            summary["lineage_native_finite_qualification"] = qualification
    for mode, rows in [("actual", actual_rows), ("adjusted", adjusted_rows)]:
        integral = integrate(rows, "estimated_busy_cpus")
        if abs(integral + (zero_actual if mode == "actual" else zero_adjusted) - cpu_seconds) > .001:
            raise ValueError("CPU-time conservation failed for " + mode)
        summary[mode + "_busy_capacity_fraction"] = cpu_seconds / (cap * summary[mode + "_elapsed_seconds"]) if summary[mode + "_elapsed_seconds"] else 0.
        summary[mode + "_concurrent_task_cpu_hours"] = integrate(rows, "concurrent_task_cpus") / 3600.
        summary[mode + "_peak_concurrent_task_cpus"] = max(r["concurrent_task_cpus"] for r in rows)
        write_csv(out / (mode + "_timeline.csv"), rows)
    summary["scheduler_adjustment_seconds"] = summary["actual_elapsed_seconds"] - summary["adjusted_elapsed_seconds"]
    if summary["adjusted_peak_concurrent_task_cpus"] > cap + 1e-6:
        raise ValueError("Replay exceeded the original CPU cap")
    records = []
    for task in tasks:
        key = task["key"]
        records.append({k: v for k, v in task.items() if k not in {"start", "end", "submit"}} |
                       {"actual_start_seconds": actual.get(key, (None, None))[0], "actual_end_seconds": actual.get(key, (None, None))[1],
                        "adjusted_start_seconds": adjusted[key][0], "adjusted_end_seconds": adjusted[key][1],
                        "intrinsic_release_delay_seconds": graph[key]["release_delay"]})
    fields = list(dict.fromkeys(key for row in records for key in row))
    write_csv(out / "tasks.csv", records, fields)
    phases = collections.defaultdict(list)
    for task in tasks:
        phases[task["phase"]].append(task)
    phase_rows = []
    for phase, members in phases.items():
        actual_members = [t for t in members if t["key"] in actual]
        phase_rows.append({"phase": phase, "category": members[0]["category"], "tasks": len(members),
                           "cpu_hours": sum(t.get("cpu_seconds", 0.) for t in members) / 3600.,
                           "task_wall_hours": sum(t.get("duration_seconds", 0.) for t in members) / 3600.,
                           "actual_start_minutes": min((actual[t["key"]][0] for t in actual_members), default=0.) / 60. if actual_members else None,
                           "actual_end_minutes": max((actual[t["key"]][1] for t in actual_members), default=0.) / 60. if actual_members else None,
                           "adjusted_start_minutes": min(adjusted[t["key"]][0] for t in members) / 60.,
                           "adjusted_end_minutes": max(adjusted[t["key"]][1] for t in members) / 60.,
                           "states": json.dumps(dict(collections.Counter(t["state"] for t in members)), sort_keys=True)})
    write_csv(out / "phases.csv", phase_rows)
    write_json(out / "summary.json", summary)
    render(out, summary, actual_rows, adjusted_rows)
    write_report(out, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
