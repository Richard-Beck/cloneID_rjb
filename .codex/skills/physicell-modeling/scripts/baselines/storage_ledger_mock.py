"""Split storage-ledger quota and crash regressions; no engines or process calls."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import copy
import fcntl
import hashlib
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import storage_budget as CANDIDATE

CONFIG=None
TEST_ROOT=None

class OriginalLayoutFixture:
    @staticmethod
    def initialize(run, config, inventory):
        # Old on-disk format fixture only; never imports an earlier implementation.
        CANDIDATE.write(run/'storage/state.json',dict(inventory=inventory,plan=CANDIDATE.storage_plan(config),native_active={},initialized_unix=0.))

BASE=OriginalLayoutFixture

def read(path):return json.loads(Path(path).read_text())

class CandidateChecks(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='cloneid_split_ledger_',dir=TEST_ROOT);self.root=Path(self.temporary.name)
        self.config=copy.deepcopy(CONFIG);self.config['storage']['native_case_slots']=4
        self.inventory=dict(bytes=1000,allocated_bytes=1000,verified=True,inventory_sha256='synthetic-inventory',dangling_symlinks=[dict(path=f'container/runtime/software/{i:04}/'+('x'*80),target='/absent/'+('y'*80),target_bytes=0) for i in range(935)])

    def tearDown(self):self.temporary.cleanup()

    def fresh(self,name='candidate',module=CANDIDATE):
        run=self.root/name;run.mkdir();module.initialize(run,self.config,self.inventory);return run

    def snapshot(self,run):return CANDIDATE.ledger_snapshot(run)

    def test_inventory_and_assets_have_full_hash_bound_audit_view(self):
        run=self.fresh();state=read(run/'storage/state.json')
        self.assertNotIn('dangling_symlinks',state['inventory']);self.assertNotIn('field_assets',state)
        self.assertEqual(state['asset_ledger']['record'],'assets.json')
        self.assertEqual(CANDIDATE.inventory_record(run),self.inventory)
        self.assertEqual(self.snapshot(run)['inventory'],self.inventory)
        self.assertEqual(self.snapshot(run)['field_assets'],{})
        self.assertLess((run/'storage/state.json').stat().st_size,10000)
        before=hashlib.sha256((run/'storage/inventory.json').read_bytes()).hexdigest()
        reserve,commit,release=CANDIDATE.asset_callbacks(run,self.config);asset=run/'field_frame_0000.bin';asset.write_bytes(b'owned');token=reserve(5,asset,dict(full_provenance='unchanged'));commit(token,dict(sha256=hashlib.sha256(b'owned').hexdigest()))
        full=self.snapshot(run);self.assertEqual(full['field_assets'][token]['provenance'],dict(full_provenance='unchanged'))
        self.assertEqual(full['field_assets'][token]['record']['sha256'],hashlib.sha256(b'owned').hexdigest())
        release(token);self.assertEqual(before,hashlib.sha256((run/'storage/inventory.json').read_bytes()).hexdigest())

    def test_concurrent_case_quota_has_no_lost_updates(self):
        run=self.fresh();barrier=threading.Barrier(5);finish=threading.Event()
        def task(index):
            with CANDIDATE.reserve_case(run,self.config,str(index),run/'transient'/str(index)):
                path=run/'transient'/str(index);path.mkdir();(path/'payload').write_bytes(b'owned');barrier.wait(timeout=3);finish.wait(timeout=3)
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs=[pool.submit(task,i) for i in range(4)];barrier.wait(timeout=3)
            self.assertEqual(len(read(run/'storage/state.json')['native_active']),4)
            try:
                with self.assertRaisesRegex(ValueError,'exhausted'):
                    with CANDIDATE.reserve_case(run,self.config,'fifth',run/'transient/fifth'):self.fail('Overallocated')
            finally:finish.set()
            for job in jobs:job.result(timeout=3)
        self.assertEqual(self.snapshot(run)['native_active'],{});self.assertEqual(list((run/'transient').iterdir()),[])

    def test_concurrent_asset_quota_uses_same_global_lock(self):
        run=self.fresh();config=copy.deepcopy(self.config);config['storage']['figure_staging_reservation_bytes']=100
        reserve,commit,release=CANDIDATE.asset_callbacks(run,config);barrier=threading.Barrier(4)
        def task(index):
            path=run/f'field_frame_{index:04}.bin';token=reserve(31,path,dict(index=index))
            if token:path.write_bytes(b'x'*31);commit(token,dict(sha256=hashlib.sha256(b'x'*31).hexdigest()))
            barrier.wait(timeout=3);return token
        with ThreadPoolExecutor(max_workers=4) as pool:tokens=list(pool.map(task,range(4)))
        assets=self.snapshot(run)['field_assets'];self.assertEqual(len(assets),3);self.assertEqual(sum(a['bytes'] for a in assets.values()),93)
        for token in tokens:release(token)
        self.assertEqual(self.snapshot(run)['field_assets'],{})
        # A global lock held externally blocks BOTH case and asset mutations.
        lock=(run/'storage/reservations.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(reserve,1,run/'field_frame_0999.bin',{})
            time.sleep(.02);self.assertFalse(future.done());fcntl.flock(lock,fcntl.LOCK_UN);token=future.result(timeout=3)
        lock.close();release(token)

    def test_startup_and_inventory_reads_wait_for_mutable_state_writer(self):
        for label, operation in [('callbacks', lambda run: CANDIDATE.asset_callbacks(run,self.config)), ('inventory', CANDIDATE.inventory_record)]:
            run=self.fresh('read_lock_'+label)
            lock=(run/'storage/reservations.lock').open('a+')
            fcntl.flock(lock,fcntl.LOCK_EX)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(operation,run)
                try:
                    time.sleep(.02)
                    self.assertFalse(future.done(),'Startup read bypassed a concurrent state writer')
                finally:
                    fcntl.flock(lock,fcntl.LOCK_UN)
                future.result(timeout=3)
            lock.close()

    def test_failed_case_keeps_overlap_lease_and_blocks_new_admission(self):
        self.config['storage']['native_case_slots']=1;run=self.fresh()
        with self.assertRaisesRegex(RuntimeError,'interrupted'):
            with CANDIDATE.reserve_case(run,self.config,'one',run/'transient/one'):
                path=run/'transient/one';path.mkdir();(path/'payload').write_bytes(b'owned');raise RuntimeError('interrupted')
        state=self.snapshot(run);self.assertTrue(state['native_active']['one']['compact_finalization_unverified']);self.assertFalse((run/'transient/one').exists())
        with self.assertRaisesRegex(ValueError,'exhausted'):
            with CANDIDATE.reserve_case(run,self.config,'two',run/'transient/two'):self.fail('Admitted')
        with self.assertRaisesRegex(ValueError,'nonempty'):
            CANDIDATE.initialize(run,self.config,self.inventory)

    def test_asset_commit_failure_retains_reserved_bytes_and_provenance(self):
        run=self.fresh();reserve,commit,release=CANDIDATE.asset_callbacks(run,self.config);asset=run/'field_frame_0000.bin';token=reserve(5,asset,dict(provenance='original'));asset.write_bytes(b'owned')
        original=CANDIDATE.write
        def fail(path,value,**kwargs):
            if Path(path).name=='assets.json':raise OSError('synthetic atomic write failure')
            return original(path,value,**kwargs)
        with patch.object(CANDIDATE,'write',side_effect=fail):
            with self.assertRaisesRegex(OSError,'synthetic'):commit(token,{'sha256':'not_committed'})
        entry=self.snapshot(run)['field_assets'][token]
        self.assertEqual(entry['status'],'reserved');self.assertEqual(entry['bytes'],5);self.assertEqual(entry['provenance'],dict(provenance='original'))
        self.assertNotIn('record',entry);release(token)

    def test_partial_initialization_cannot_publish_ready_generation(self):
        run=self.fresh('old_layout',BASE);original=CANDIDATE.write
        def fail(path,value,**kwargs):
            if Path(path).name=='state.json' and value.get('asset_ledger',{}).get('ready') is True:raise OSError('synthetic final readiness failure')
            return original(path,value,**kwargs)
        with patch.object(CANDIDATE,'write',side_effect=fail):
            with self.assertRaisesRegex(OSError,'readiness'):CANDIDATE.initialize(run,self.config,self.inventory)
        self.assertFalse(read(run/'storage/state.json')['asset_ledger']['ready'])
        with self.assertRaisesRegex(ValueError,'not ready'):CANDIDATE.asset_callbacks(run,self.config)
        with self.assertRaisesRegex(ValueError,'not ready'):
            with CANDIDATE.reserve_case(run,self.config,'one',run/'transient/one'):self.fail('Admitted')

    def test_interrupted_reinitialization_cannot_mix_split_generations(self):
        run=self.fresh();before=read(run/'storage/state.json')['asset_ledger']['ledger_id'];original=CANDIDATE.write
        CANDIDATE.asset_callbacks(run,self.config)  # Populate the old-generation startup cache first.
        def fail(path,value,**kwargs):
            if Path(path).name=='state.json' and value.get('asset_ledger',{}).get('ready') is True:raise OSError('synthetic final readiness failure')
            return original(path,value,**kwargs)
        with patch.object(CANDIDATE,'write',side_effect=fail):
            with self.assertRaisesRegex(OSError,'readiness'):CANDIDATE.initialize(run,self.config,self.inventory)
        self.assertFalse(read(run/'storage/state.json')['asset_ledger']['ready'])
        self.assertNotEqual(read(run/'storage/assets.json')['ledger_id'],before)
        with self.assertRaisesRegex(ValueError,'not ready'):CANDIDATE.asset_callbacks(run,self.config)
        with self.assertRaisesRegex(ValueError,'not ready'):
            with CANDIDATE.reserve_case(run,self.config,'one',run/'transient/one'):self.fail('Admitted mixed generation')

    def test_asset_initialization_failure_keeps_explicit_unready_marker(self):
        run=self.fresh('asset_init_failure',BASE);original=CANDIDATE.write
        def fail(path,value,**kwargs):
            if Path(path).name=='assets.json':raise OSError('synthetic asset initialization failure')
            return original(path,value,**kwargs)
        with patch.object(CANDIDATE,'write',side_effect=fail):
            with self.assertRaisesRegex(OSError,'initialization'):CANDIDATE.initialize(run,self.config,self.inventory)
        self.assertFalse(read(run/'storage/state.json')['asset_ledger']['ready'])
        with self.assertRaisesRegex(ValueError,'not ready'):CANDIDATE.asset_callbacks(run,self.config)
        with self.assertRaisesRegex(ValueError,'not ready'):
            with CANDIDATE.reserve_case(run,self.config,'one',run/'transient/one'):self.fail('Admitted after asset init failure')

    def test_corrupted_inventory_is_rejected_at_start_and_audit(self):
        run=self.fresh();(run/'storage/inventory.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):CANDIDATE.inventory_record(run)
        with self.assertRaisesRegex(ValueError,'hash mismatch'):CANDIDATE.asset_callbacks(run,self.config)
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.snapshot(run)

    def test_cleanup_uses_unchanged_asset_hash_and_path_guards(self):
        run=self.fresh();reserve,commit,release=CANDIDATE.asset_callbacks(run,self.config)
        keep=run/'field_frame_0000.bin';lose=run/'field_frame_0001.bin'
        for path in [keep,lose]:
            token=reserve(5,path,{});path.write_bytes(b'owned');commit(token,dict(sha256=hashlib.sha256(b'owned').hexdigest()))
        result=CANDIDATE.cleanup_unretained_assets(run,[keep.name]);self.assertTrue(keep.exists());self.assertFalse(lose.exists());self.assertEqual(len(self.snapshot(run)['field_assets']),1)
        keep.write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError,'differs'):CANDIDATE.cleanup_unretained_assets(run,[])

def run(out, config, check):
    global CONFIG, TEST_ROOT
    CONFIG=config;TEST_ROOT=Path(out)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(CandidateChecks)
    result=unittest.TestResult();suite.run(result)
    if result.errors or result.failures:
        raise AssertionError('Split-ledger regressions failed: '+str(result.errors+result.failures))
    check('split_storage_ledger_quota_crash_and_audit_regressions_'+str(result.testsRun),result.wasSuccessful())
    return result.testsRun
