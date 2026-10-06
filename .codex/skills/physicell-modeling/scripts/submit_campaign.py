"""Submit stage dependencies, streaming each candidate through a shared capped array.

Dry run is the default. All jobs are held until task dependencies are configured.
"""
import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path
from core.fitting import atomic_json


def positive(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(label + ' must be a positive integer')
    return value


def argv(command):
    if not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command):
        raise ValueError('command must be argv strings')
    return command


def stream_groups(node):
    """Fit and finalization tasks precede candidate-specific trajectory ranges."""
    counts = node['trajectories_per_candidate']
    if not isinstance(counts, list) or not counts:
        raise ValueError('Provide a nonempty trajectories_per_candidate list')
    for count in counts:
        positive(count, 'trajectory count')
    size = len(counts)
    groups = []
    for phase in ('fit', 'finalize', 'simulate'):
        positive(node[phase]['minutes'], phase + ' minutes')
        argv(node[phase]['command'])
    for candidate in range(size):
        groups.append(dict(first=candidate, last=candidate, phase='fit', candidate=candidate,
                           local_first=candidate, parent=None, command=node['fit']['command'], minutes=node['fit']['minutes']))
    for candidate in range(size):
        groups.append(dict(first=size + candidate, last=size + candidate, phase='finalize',
                           candidate=candidate, local_first=candidate, parent=candidate, command=node['finalize']['command'], minutes=node['finalize']['minutes']))
    cursor = 2 * size
    local = 0
    for candidate, count in enumerate(counts):
        groups.append(dict(first=cursor, last=cursor + count - 1, phase='simulate', candidate=candidate,
                           local_first=local, parent=size + candidate, command=node['simulate']['command'], minutes=node['simulate']['minutes']))
        cursor += count
        local += count
    return groups, cursor


def plan(spec, out):
    cpus = positive(spec['max_cpus'], 'max_cpus')
    seen, result = [], []
    for node in spec['nodes']:
        name = node['name']
        if not name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in name) or name in seen:
            raise ValueError('Invalid/duplicate node name')
        previous = seen[-1] if seen else None
        if node.get('depends_on') != previous:
            raise ValueError('Stage nodes must form a chain; use kind=stream for within-stage overlap')
        condition = node.get('condition', 'afterok')
        if condition not in ('afterok', 'afterany'):
            raise ValueError('Invalid dependency condition')
        kind = node.get('kind', 'command')
        groups = None
        if kind == 'stream':
            groups, tasks = stream_groups(node)
            minutes = max(group['minutes'] for group in groups)
            manifest = out / (name + '_tasks.json')
            command = [spec.get('python', sys.executable), str(Path(__file__).with_name('run_campaign_task.py').resolve()), str(manifest)]
        elif kind == 'command':
            tasks = positive(node.get('tasks', 1), 'tasks')
            minutes = positive(node['minutes'], 'minutes')
            command = argv(node['command'])
        else:
            raise ValueError('Unknown node kind: ' + kind)
        script = out / (name + '.sh')
        lines = ['#!/bin/bash', 'set -euo pipefail',
                 'export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1',
                 'export SLURM_ARRAY_TASK_ID=${SLURM_ARRAY_TASK_ID:-0}',
                 'cd ' + shlex.quote(str(Path(node['cwd']).resolve())), 'exec ' + shlex.join(command)]
        cmd = ['sbatch', '--parsable', '--hold', '--kill-on-invalid-dep=yes', '--ntasks=1', '--cpus-per-task=1',
               f'--mem={node.get("memory", "6G")}', f'--time={minutes}', f'--job-name=pc_{name}',
               f'--output={out}/{name}_%A_%a.log']
        for key in ('partition', 'qos', 'account'):
            if spec.get(key):
                cmd.append('--' + key + '=' + str(spec[key]))
        if tasks > 1:
            # A single cap covers fit, finalization and simulation concurrently.
            throttle = f'%{cpus}' if tasks > cpus else ''
            cmd.append(f'--array=0-{tasks - 1}{throttle}')
        entry = dict(name=name, kind=kind, script=str(script), script_text='\n'.join(lines) + '\n',
                     command=cmd, tasks=tasks, minutes=minutes, depends_on=previous, condition=condition)
        if groups is not None:
            entry.update(manifest=str(manifest), task_groups=groups)
        result.append(entry)
        seen.append(name)
    if not result:
        raise ValueError('No nodes')
    return result


def dependency(node, jobs):
    return node['condition'] + ':' + jobs[node['depends_on']] if node['depends_on'] else ''


def configuration_commands(node, job, jobs):
    """Materialize parents before attaching dependencies within the same array."""
    external = dependency(node, jobs)
    for group in node.get('task_groups', []):
        first, last = group['first'], group['last']
        selector = str(first) if first == last else f'[{first}-{last}]'
        command = ['scontrol', 'update', f'JobId={job}_{selector}', f'TimeLimit={group["minutes"]}']
        deps = [external] if external else []
        if group['parent'] is not None:
            deps.append(f'afterany:{job}_{group["parent"]}')
        if deps:
            command.append('Dependency=' + ','.join(deps))
        yield command


def launch(spec, out, submit=False, run=subprocess.check_output):
    nodes = plan(spec, out)
    if (out / 'jobs.json').exists():
        raise FileExistsError('Existing submission; resume deliberately with missing-task manifest in a new submission_root')
    if submit and not spec.get('scientific_contract_confirmed'):
        raise ValueError('Record existing user confirmation of scientific contract before submitting')
    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / 'specification.json', spec)
    atomic_json(out / 'plan.json', nodes)
    atomic_json(out / 'launcher_provenance.json', {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__), Path(__file__).with_name('run_campaign_task.py'))})
    jobs, operations, released = {}, [], []
    try:
        for node in nodes:
            Path(node['script']).write_text(node['script_text'])
            if node['kind'] == 'stream':
                atomic_json(node['manifest'], node['task_groups'])
            command = node['command'].copy()
            external = dependency(node, jobs)
            if external:
                command.append('--dependency=' + external)
            command.append(node['script'])
            operations.append(command)
            if submit:
                job = run(command, text=True).strip().split(';')[0]
                if not job.isdigit():
                    raise RuntimeError('Unexpected sbatch response: ' + job)
            else:
                job = 'DRY_' + node['name']
            jobs[node['name']] = job
            if submit:
                atomic_json(out / 'jobs.json', jobs)
            for command in configuration_commands(node, job, jobs):
                operations.append(command)
                if submit:
                    run(command, text=True)
        # No work can run before all internal dependencies and downstream jobs exist.
        for job in jobs.values():
            command = ['scontrol', 'release', job]
            operations.append(command)
            if submit:
                run(command, text=True)
                released.append(job)
        state = 'released' if submit else 'dry_run'
    except BaseException as error:
        atomic_json(out / 'submission_status.json', dict(state='interrupted', error=str(error), jobs=jobs, released=released,
                    recovery='Inspect recorded jobs before resuming. Unreleased jobs remain held; never blindly resubmit.'))
        raise
    finally:
        atomic_json(out / 'scheduler_commands.json', operations)
    atomic_json(out / 'submission_status.json', dict(state=state, jobs=jobs, released=released))
    return dict(submitted=submit, jobs=jobs, plan=str(out / 'plan.json'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('spec')
    parser.add_argument('--submit', action='store_true')
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text())
    print(json.dumps(launch(spec, Path(spec['submission_root']).resolve(), args.submit), indent=2))


if __name__ == '__main__':
    main()
