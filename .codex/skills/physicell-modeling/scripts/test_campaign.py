"""Synthetic scheduler checks; subprocess calls are mocked, no jobs are submitted."""
import json
import tempfile
import unittest
from pathlib import Path
from run_campaign_task import task_context
from submit_campaign import launch, plan, configuration_commands


def fixture():
    return dict(max_cpus=3, scientific_contract_confirmed=True, nodes=[
        dict(name='prepare', cwd='.', command=['true'], minutes=1),
        dict(name='stationary', kind='stream', cwd='.', depends_on='prepare',
             trajectories_per_candidate=[2, 3],
             fit=dict(command=['adapter', 'fit'], minutes=5),
             finalize=dict(command=['adapter', 'finalize'], minutes=2),
             simulate=dict(command=['adapter', 'simulate'], minutes=20)),
        dict(name='score', cwd='.', command=['adapter', 'score'], minutes=1,
             depends_on='stationary', condition='afterany'),
        dict(name='child_prepare', cwd='.', command=['adapter', 'prepare'], minutes=1,
             depends_on='score', condition='afterok')])


class CampaignTests(unittest.TestCase):
    def test_stream_dependencies_and_shared_cap(self):
        nodes = plan(fixture(), Path('/tmp/unused-plan'))
        stream = nodes[1]
        self.assertEqual(stream['tasks'], 9)
        self.assertIn('--array=0-8%3', stream['command'])
        groups = stream['task_groups']
        self.assertEqual([(g['first'], g['last'], g['parent']) for g in groups],
                         [(0, 0, None), (1, 1, None), (2, 2, 0), (3, 3, 1), (4, 5, 2), (6, 8, 3)])
        commands = list(configuration_commands(stream, '12', {'prepare': '11'}))
        self.assertIn('Dependency=afterok:11,afterany:12_2', commands[4])
        self.assertIn('JobId=12_[4-5]', commands[4])
        self.assertIn('TimeLimit=5', commands[0])
        self.assertIn('TimeLimit=2', commands[2])
        self.assertIn('TimeLimit=20', commands[4])
        # Candidate 0 simulation can run while candidate 1 fitting remains unfinished.
        completed = {0, 2}
        ready = [g for g in groups if g['parent'] in completed and g['first'] not in completed]
        self.assertEqual([(g['first'], g['last']) for g in ready], [(4, 5)])
        # Parent ranking remains a whole-stage barrier, not a partial/approximate pool.
        self.assertEqual(nodes[2]['depends_on'], 'stationary')
        self.assertEqual(nodes[2]['condition'], 'afterany')
        self.assertEqual(nodes[3]['depends_on'], 'score')
        self.assertEqual(nodes[3]['condition'], 'afterok')

    def test_adapter_indices(self):
        groups = plan(fixture(), Path('/tmp/unused-plan'))[1]['task_groups']
        command, env = task_context(groups, 8)
        self.assertEqual(command, ['adapter', 'simulate'])
        self.assertEqual(env['SLURM_ARRAY_TASK_ID'], '4')
        self.assertEqual(env['PHYSICELL_ARRAY_TASK_ID'], '8')
        self.assertEqual(env['PHYSICELL_CANDIDATE_INDEX'], '1')
        self.assertEqual(env['PHYSICELL_TRAJECTORY_INDEX'], '2')
        self.assertEqual(task_context(groups, 3)[1]['SLURM_ARRAY_TASK_ID'], '1')
        with self.assertRaises(ValueError):
            task_context(groups, 9)

    def test_submit_holds_everything_until_configured(self):
        calls = []
        def run(command, text):
            calls.append(command)
            if command[0] == 'sbatch':
                return str(100 + sum(c[0] == 'sbatch' for c in calls)) + '\n'
            return ''
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            launch(fixture(), out, submit=True, run=run)
            first_release = next(i for i, c in enumerate(calls) if c[:2] == ['scontrol', 'release'])
            self.assertTrue(all(c[0] == 'scontrol' and c[1] == 'release' for c in calls[first_release:]))
            self.assertEqual(sum(c[0] == 'sbatch' for c in calls[:first_release]), 4)
            self.assertTrue(all('--hold' in c for c in calls if c[0] == 'sbatch'))
            self.assertEqual(json.loads((out / 'submission_status.json').read_text())['state'], 'released')
            with self.assertRaises(FileExistsError):
                launch(fixture(), out, submit=True, run=run)

    def test_configuration_failure_keeps_jobs_held_and_recorded(self):
        calls = []
        def run(command, text):
            calls.append(command)
            if command[0] == 'sbatch':
                return str(100 + sum(c[0] == 'sbatch' for c in calls))
            raise RuntimeError('injected scontrol failure')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                launch(fixture(), out, submit=True, run=run)
            state = json.loads((out / 'submission_status.json').read_text())
            self.assertEqual(state['state'], 'interrupted')
            self.assertEqual(state['released'], [])
            self.assertEqual(len(state['jobs']), 2)
            self.assertFalse(any(c[:2] == ['scontrol', 'release'] for c in calls))

    def test_dry_run_never_calls_scheduler_and_small_array_needs_no_throttle(self):
        spec = fixture()
        spec['max_cpus'] = 20
        with tempfile.TemporaryDirectory() as tmp:
            launch(spec, Path(tmp), run=lambda *a, **k: self.fail('dry-run scheduler call'))
            self.assertFalse((Path(tmp) / 'jobs.json').exists())
            self.assertIn('--array=0-8', plan(spec, Path(tmp))[1]['command'])
        spec['nodes'][1]['trajectories_per_candidate'] = [0]
        with self.assertRaises(ValueError):
            plan(spec, Path('/tmp/unused-plan'))


if __name__ == '__main__':
    unittest.main()
