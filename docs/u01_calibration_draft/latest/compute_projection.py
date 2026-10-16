"""Fixed objective-call budget projection using measured native TotalCPU.

Reads frozen campaign artifacts and a saved accounting snapshot; never submits jobs,
runs objectives, or treats CPU allocations as measured use.
"""
import csv
import io
import re
import numpy as np


def seconds(value):
    days = 0
    if '-' in value:
        d, value = value.split('-', 1)
        days = int(d)
    return days*86400 + sum(float(x)*60**i for i, x in enumerate(value.split(':')[::-1]))


def project(lineage, perspective, local_accounting, read, track):
    lroot, proot = lineage['root'], perspective['root']
    usage = lineage['report']['compute_usage']
    pusage = read(proot/'report/compute.json')
    lrows = list(csv.DictReader(io.StringIO(track(lroot/'audit/all_slurm_accounting.psv', 'measured lineage task CPU accounting').read_text()), delimiter='|'))
    lcpu = {r['JobID']: seconds(r['TotalCPU'])/3600 for r in lrows if re.fullmatch(r'\d+(?:_\d+)?', r['JobID'])}
    jobs = read(lroot/'submissions/campaign/jobs.json')
    stages = []
    lsearch = 0.
    for stage, slots_per_call in [('shared', 16), ('ridge', 32)]:
        candidates = read(lroot/f'{stage}_candidates.json')
        statuses = [read(lroot/'candidates'/c['id']/'checkpoint.json.status.json') for c in candidates]
        n = sum(s['evaluations'] for s in statuses)
        manifest = read(lroot/f'submissions/campaign/{stage}_stream_tasks.json')
        job = jobs[f'{stage}_stream']
        costs = {c['id']: 0. for c in candidates}
        counts = {c['id']: 0 for c in candidates}
        for task in manifest:
            for i in range(task['first'], task['last']+1):
                cost = lcpu[f'{job}_{i}']
                if task['phase'] == 'fit':
                    lsearch += cost
                elif task['phase'] == 'simulate':
                    cid = candidates[task['candidate']]['id']
                    costs[cid] += cost
                    counts[cid] += 1
        scores = read(lroot/f'{stage}_scores.json')
        complete = [s for s in scores if s['status'] == 'complete']
        benchmark = []
        for score in complete:
            cid = score['candidate']['id']
            slots = read(lroot/'candidates'/cid/'slots.json')
            assert counts[cid] == len(slots) == slots_per_call
            assert sorted({s['replicate'] for s in slots}) == [0, 1]
            assert len({i for s in slots for i in s['indices']}) == 343
            benchmark.append(dict(candidate=cid, cpu_hours=costs[cid], native_tasks=len(slots)))
        values = [b['cpu_hours'] for b in benchmark]
        excluded = [dict(candidate=s['candidate']['id'], score_status=s['status'],
                         measured_cpu_hours=costs[s['candidate']['id']],
                         accounted_native_tasks=counts[s['candidate']['id']],
                         failed_slots=s.get('failed_slots', [])) for s in scores if s['status'] != 'complete']
        assert all(counts[c['id']] == slots_per_call for c in candidates)
        stages.append(dict(stage=stage, objective_calls=n, full_observations=343, native_replicates=2,
                           native_tasks_per_call=slots_per_call, complete_benchmark_calls=len(values),
                           mean_cpu_hours_per_call=float(np.mean(values)),
                           sensitivity_cpu_hours_per_call=np.quantile(values, [.1, .9]).tolist(),
                           benchmark=benchmark, excluded_from_complete_benchmark=excluded,
                           all_candidate_accounting_available=True,
                           all_attempts_mean_cpu_hours_per_call=float(np.mean(list(costs.values()))),
                           exclusion_reason='Frozen aggregate scientific score incomplete/nonfinite, not unavailable CPU accounting',
                           selection_bias_caveat='Complete objectives may omit costly failures or fast empty/invalid fields; benchmark spread does not cover the whole optimization domain'))
    assert sum(s['objective_calls'] for s in stages) == usage['Approximation objective calls'] == 34667
    lused = usage['Measured SLURM CPU-hours']
    lretained = lused-lsearch
    lprojected = lretained+sum(s['objective_calls']*s['mean_cpu_hours_per_call'] for s in stages)
    lrange = [lretained+sum(s['objective_calls']*s['sensitivity_cpu_hours_per_call'][i] for s in stages) for i in [0, 1]]

    raw = list(csv.reader(io.StringIO(track(local_accounting, 'saved measured perspective task TotalCPU accounting with array indices').read_text()), delimiter='|'))
    prows = {r[0]: r for r in raw if len(r) >= 5 and re.fullmatch(r'\d+(?:_\d+)?', r[0])}
    pcpu = {jid: seconds(r[3])/3600 for jid, r in prows.items()}
    assert all(int(r[4]) == 1 for r in prows.values())
    exploration_job = read(proot/'submissions/exploration/jobs.json')['no_wgd_1000_explore']
    refinement_job = '21036740'  # Frozen native-informed refinement array in this concluded pilot.
    psearch = sum(cpu for jid, cpu in pcpu.items() if jid.startswith(str(exploration_job)+'_') or jid.startswith(refinement_job+'_'))
    candidates = read(proot/'candidates.json')
    ne = sum(read(proot/'candidates'/c['id']/'checkpoint.json.status.json')['evaluations'] for c in candidates)
    refinement = read(proot/'audit/refinement_summary.json')
    nr = sum(read(proot/'refinement'/row['candidate_id']/'final.json')['evaluations'] for row in refinement['rows'])
    assert ne == read(proot/'audit/exploration_summary.json')['evaluations_total'] == 53016
    assert nr == refinement['evaluations_total'] == 556
    final_job = read(proot/'final_validation/submission.json')['native_job']
    slots = read(proot/'final_validation/slots.json')
    report = read(proot/'report/report_data.json')
    samples = []
    for result in report:
        summary = result['summary']
        if not summary['native_evaluation_complete']:
            continue
        cid = result['id']
        parts = {}
        for kind in ['main', 'minority_probe']:
            ss = [s for s in slots if s['candidate_id'] == cid and s['kind'] == kind]
            assert len(ss) == (472 if kind == 'main' else 128)
            assert {s['replicate'] for s in ss} == set(range(4))
            parts[kind] = sum(pcpu[f'{final_job}_{s["case_index"]}'] for s in ss)
        samples.append(dict(candidate=cid, main_cpu_hours=parts['main'], probe_cpu_hours=parts['minority_probe'],
                            cpu_hours=sum(parts.values()), main_cases=472, probe_cases=128, native_replicates=4))
    assert len(samples) == 2  # Displayed example's failed probe is excluded from a complete-call benchmark.
    mean = float(np.mean([s['cpu_hours'] for s in samples]))
    pused = pusage['actual_cpu_hours']
    pretained = pused-psearch
    pprojected = pretained+(ne+nr)*mean
    prange = [pretained+(ne+nr)*float(f([s['cpu_hours'] for s in samples])) for f in [min, max]]
    screen_job = read(proot/'screen/submission.json')['native_job']
    screen_slots = read(proot/'screen/slots.json')
    screen_cost = sum(pcpu[f'{screen_job}_{s["case_index"]}'] for s in screen_slots)/40
    return dict(
        method='Fixed evaluation-budget replacement: retained measured CPU + sum(recorded analytical calls * mean matched complete-native-call CPU)',
        estimator='Mean measured TotalCPU of complete native objectives; no CPU allocation enters the estimate',
        fixed_budget_caveat='Same number of objective calls, not equal convergence, parameters, wall time or optimization trajectory',
        native_benchmark_caveat='Benchmarks are optimized candidate checkpoints; costs elsewhere in the search can differ',
        perspective_closure_caveat='One full-support native batch per call at frozen culture mixtures. Additional pure-native composition-history closure iterations, native correction fitting and analytical closure guidance without a measured pure-native counterpart are not priced; this is a conditional cost scenario, not a measured pure-native optimization',
        retained_cost_scope='All recorded campaign CPU outside analytical exploratory/refinement fitting, including planned native checks and report jobs; local unscheduled work remains excluded',
        lineage=dict(used_cpu_hours=lused, analytical_search_cpu_hours=lsearch, retained_other_cpu_hours=lretained,
                     stages=stages, projected_cpu_hours=lprojected, benchmark_sensitivity_cpu_hours=lrange,
                     sensitivity_note='10th/90th percentile complete-native-call costs within each stage; descriptive, not confidence limits'),
        perspective=dict(used_cpu_hours=pused, analytical_search_cpu_hours=psearch, retained_other_cpu_hours=pretained,
                         exploratory_calls=ne, refinement_calls=nr, full_observations=343, passages=118, native_replicates=4,
                         mean_cpu_hours_per_call=mean, complete_benchmark_calls=len(samples), benchmark=samples,
                         excluded_display_candidate_reason='127/128 probes; no failed-probe runtime is treated as a successful full objective',
                         screening_support=dict(passages=24, native_replicates=2, main_cases=48, probe_cases=64,
                                                mean_cpu_hours_per_candidate=screen_cost, used_for_primary_projection=False),
                         projected_cpu_hours=pprojected, benchmark_sensitivity_cpu_hours=prange,
                         two_seed_cost_sensitivity_projected_cpu_hours=pretained+(ne+nr)*mean/2,
                         sensitivity_note='Range across the two complete finalist benchmark calls; descriptive, not confidence limits'))
