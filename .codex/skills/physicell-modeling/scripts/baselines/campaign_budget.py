"""One execution window, bounded scientific admission, and saved-evidence harvest."""
from pathlib import Path
import datetime
import json
import os
import signal
import subprocess
import time


def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def initialize(run,config,clock=time.time):
    import workflow as w
    run=Path(run);path=run/'budget/clock.json'
    if path.exists():raise ValueError('Execution budget clock already initialized')
    epoch=clock();r=config['resources']
    record={'start_unix':epoch,'start_utc':now(),'science_deadline_unix':epoch+r['science_window_seconds'],'report_deadline_unix':epoch+r['execution_window_seconds'],'execution_window_seconds':r['execution_window_seconds'],'cpu_hour_ceiling':r['budget_cpu_hours_cap'],'max_concurrent_cpus':r['max_concurrent_cpus'],'queue_policy':'Starts on allocated budget-start worker; subsequent dependency/queue delay is visible execution-window time; pre-submission waiting is excluded','report_reserved_seconds':r['report_reserve_seconds']}
    w.write(path,record);return record


def remaining(run,scientific=True,clock=time.time):
    path=Path(run)/'budget/clock.json'
    if not path.exists():return None
    value=json.loads(path.read_text());key='science_deadline_unix' if scientific else 'report_deadline_unix'
    return max(0.,value[key]-clock())


def admitted(run,minimum_seconds=1.,clock=time.time):
    value=remaining(run,clock=clock)
    return value is None or value>=minimum_seconds


def clip_seconds(run,requested,clock=time.time):
    value=remaining(run,clock=clock)
    return float(requested) if value is None else max(0.,min(float(requested),value))


def controller(run,config,executor=None,sleep=time.sleep,clock=time.time):
    """Only this run's ledger jobs are stopped; no new scientific work is added."""
    import workflow as w
    import storage_budget
    import budget_harvest
    run=Path(run);submission=w.read(run/'scheduler_submission.json');jobs=submission['jobs'];own=str(os.environ.get('SLURM_ARRAY_JOB_ID') or os.environ.get('SLURM_JOB_ID',''))
    if executor is None:executor=lambda argv:subprocess.run(argv,text=True,capture_output=True,check=True).stdout
    actions=[]
    def action(argv):
        entry={'utc':now(),'argv':argv};actions.append(entry);w.write(run/'budget/actions.json',actions)
        try:entry['result']=executor(argv);entry['returncode']=0
        except Exception as error:entry['error']=repr(error);entry['returncode']=getattr(error,'returncode',None)
        w.write(run/'budget/actions.json',actions)
    while True:
        if (run/'report/REPORT.md').exists():
            # Reporting has written its saved evidence; its accounting finally may
            # still be running. Avoid deleting any cache until all science ends.
            states=executor(['squeue','-r','-h','-j',','.join(jobs.values()),'-o','%F|%T'])
            active=[line for line in str(states).splitlines() if line.split('|')[0] not in {own,str(jobs.get('budget_janitor',''))}]
            if not active:
                cleanup=storage_budget.cleanup_transient(run)
                import shutil
                if (run/'cache').exists():shutil.rmtree(run/'cache')
                w.write(run/'budget/controller_outcome.json',{'status':'normal_report_complete','cleanup':cleanup,'utc':now()});return
        if remaining(run,clock=clock)<=0:break
        sleep(min(5.,max(.1,remaining(run,clock=clock))))
    w.write(run/'budget/harvest_started.json',{'utc':now(),'reason':'scientific execution window exhausted; keep actual saved evidence'})
    targets=[jid for name,jid in jobs.items() if str(jid)!=own and name not in {'verify_frozen_inputs','budget_start','budget_janitor'}]
    # scancel's normal TERM/KILL sequence gives native workers a cleanup chance.
    if targets:action(['scancel',*targets])
    stop_until=min(clock()+45.,w.read(run/'budget/clock.json')['report_deadline_unix']-30.)
    while clock()<stop_until:
        state=executor(['squeue','-r','-h','-j',','.join(targets),'-o','%F|%T']) if targets else ''
        if not str(state).strip():break
        sleep(1.)
    if targets:
        state=executor(['squeue','-r','-h','-j',','.join(targets),'-o','%F|%T'])
        if str(state).strip():action(['scancel','--signal=KILL',*targets]);sleep(1.)
    final_state=executor(['squeue','-r','-h','-j',','.join(targets),'-o','%F|%T']) if targets else ''
    quiescent=not str(final_state).strip()
    cleanup=storage_budget.cleanup_transient(run) if quiescent else {'cleanup_pending':True,'reason':'Workers still owned by scheduler after termination; preserve disk reservations until dependent janitor runs','remaining_allocations':str(final_state).splitlines()}
    if not quiescent:
        w.write(run/'budget/controller_outcome.json',{'status':'cleanup_and_harvest_pending','cleanup':cleanup,'utc':now(),'no_new_fits_or_native_batch':True})
        return
    # This helper only reads stable saved current-run records and writes summaries.
    harvest=budget_harvest.harvest(run,config)
    try:
        import scheduler
        scheduler.collect_accounting(run)
    except Exception as error:w.write(run/'budget/accounting_error.json',{'error':repr(error),'utc':now()})
    w.report_run(run)
    import shutil
    if quiescent and (run/'cache').exists():shutil.rmtree(run/'cache')
    w.write(run/'budget/controller_outcome.json',{'status':'harvested_at_budget','harvest':harvest,'cleanup':cleanup,'utc':now(),'remaining_report_seconds':remaining(run,scientific=False,clock=clock),'no_new_fits_or_native_batch':True})


def janitor(run,config,executor=None):
    """Runs after every campaign job ends, including crashed controllers/workers."""
    import workflow as w
    import storage_budget
    import shutil
    run=Path(run);jobs=w.read(run/'scheduler_submission.json')['jobs'];targets=[str(job) for name,job in jobs.items() if name!='budget_janitor']
    if executor is None:executor=lambda argv:subprocess.run(argv,text=True,capture_output=True,check=True).stdout
    active=executor(['squeue','-r','-h','-j',','.join(targets),'-o','%F|%T'])
    if str(active).strip():raise ValueError('Janitor cannot release reservations while campaign allocations remain')
    result=storage_budget.cleanup_transient(run)
    if (run/'cache').exists():shutil.rmtree(run/'cache')
    state=w.read(run/'storage/state.json');state['native_active']={};w.write(run/'storage/state.json',state)
    import budget_harvest
    terminal=budget_harvest.harvest(run,config)
    retention=budget_harvest.asset_retention_plan(run,terminal)
    pruned=budget_harvest.prune_assets(run,retention,release_asset=storage_budget.asset_callbacks(run,config)[2])
    orphaned=storage_budget.cleanup_unretained_assets(run,[a['path'] for a in retention['assets'] if a['retention']=='keep'])
    # Also repairs missing reports after a controller/report-worker hard failure.
    w.report_run(run)
    w.write(run/'budget/janitor_outcome.json',{'utc':now(),'cleanup':result,'asset_pruning':pruned,'orphan_field_cleanup':orphaned,'all_other_allocations_ended':True,'scientific_calls':0})
    return result
