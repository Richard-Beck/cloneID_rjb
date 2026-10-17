"""Reconstruct the fixed-call-budget estimate from bundled measured aggregates.

Inputs are frozen objective counters and native complete-objective TotalCPU sums,
not allocations. This module performs no optimization or scheduler access.
"""
import numpy as np


def project(path, read):
    saved = read(path)
    lineage = saved["lineage"]
    perspective = saved["perspective"]
    stages = []
    for stage in lineage["stages"]:
        values = [item["cpu_hours"] for item in stage["benchmark"]]
        assert values and all(item["native_tasks"] == stage["native_tasks_per_call"] for item in stage["benchmark"])
        stages.append(dict(stage, complete_benchmark_calls=len(values),
            mean_cpu_hours_per_call=float(np.mean(values)),
            sensitivity_cpu_hours_per_call=np.quantile(values, [.1, .9]).tolist()))
    lretained = lineage["used_cpu_hours"] - lineage["analytical_search_cpu_hours"]
    lprojected = lretained + sum(stage["objective_calls"]*stage["mean_cpu_hours_per_call"] for stage in stages)
    lrange = [lretained+sum(stage["objective_calls"]*stage["sensitivity_cpu_hours_per_call"][i] for stage in stages) for i in [0, 1]]
    costs = []
    for item in perspective["benchmark"]:
        assert item["main_cases"] == 472 and item["probe_cases"] == 128 and item["native_replicates"] == 4
        assert item["main_cpu_hours"] + item["probe_cpu_hours"] == item["cpu_hours"]
        costs.append(item["cpu_hours"])
    assert len(costs) == 2
    mean = float(np.mean(costs))
    pretained = perspective["used_cpu_hours"] - perspective["analytical_search_cpu_hours"]
    calls = perspective["exploratory_calls"] + perspective["refinement_calls"]
    pprojected = pretained + calls*mean
    prange = [pretained + calls*float(f(costs)) for f in [min, max]]
    assert [lprojected, pprojected] == saved["expected_projection_cpu_hours"]
    result = {key: saved[key] for key in ["method", "estimator", "fixed_budget_caveat", "native_benchmark_caveat", "perspective_closure_caveat", "retained_cost_scope"]}
    result.update(lineage=dict(lineage, stages=stages, retained_other_cpu_hours=lretained,
                              projected_cpu_hours=lprojected, benchmark_sensitivity_cpu_hours=lrange),
                  perspective=dict(perspective, retained_other_cpu_hours=pretained,
                                   mean_cpu_hours_per_call=mean, projected_cpu_hours=pprojected,
                                   benchmark_sensitivity_cpu_hours=prange,
                                   two_seed_cost_sensitivity_projected_cpu_hours=pretained+calls*mean/2))
    return result
