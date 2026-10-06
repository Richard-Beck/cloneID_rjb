"""Dispatch one task from a stage's shared Slurm array; no polling or job submission."""
import json
import os
import sys


def task_context(groups, index):
    for group in groups:
        if group['first'] <= index <= group['last']:
            offset = index - group['first']
            env = dict(PHYSICELL_ARRAY_TASK_ID=str(index), PHYSICELL_PHASE=group['phase'],
                       PHYSICELL_CANDIDATE_INDEX=str(group['candidate']),
                       SLURM_ARRAY_TASK_ID=str(group['local_first'] + offset))
            if group['phase'] == 'simulate':
                env['PHYSICELL_TRAJECTORY_INDEX'] = str(offset)
            return group['command'], env
    raise ValueError('Task index is outside the frozen manifest')


def main():
    groups = json.load(open(sys.argv[1]))
    command, context = task_context(groups, int(os.environ['SLURM_ARRAY_TASK_ID']))
    env = os.environ.copy()
    env.pop('PHYSICELL_TRAJECTORY_INDEX', None)
    env.update(context)
    os.execvpe(command[0], command, env)


if __name__ == '__main__':
    main()
