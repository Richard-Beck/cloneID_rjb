"""Project-wide byte accounting and finite native-case reservations (decimal GB).

The compact engine protocol bounds a frame before it is written. Reservations
count every simultaneous case, independent of filesystem or scratch location.
"""
from pathlib import Path
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import shutil
import time

GB=10**9


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n');temp.replace(path)


def storage_plan(config,prepared=None):
    s=config['storage'];r=config['resources']
    durable=s['durable_limit_bytes'];transient=s['total_peak_limit_bytes']
    slots=s['native_case_slots'];case=s['case_reservation_bytes']
    estimated=s['existing_project_bytes_estimate']+s['new_durable_bytes_reservation']
    basis=s['case_count_basis'];prepared=prepared or {};l=config['lineage'];p=config['perspective'];c=p['conditional']
    oxygen=len(prepared['oxygen_values']) if prepared.get('oxygen_values') else basis['oxygen_levels'];episodes=prepared.get('episodes',basis['final_passages'])
    native_cases=l['native_pool']['shared']*oxygen*l['replicates']+l['native_pool']['ridge_per_alpha']*len(l['alphas'])*oxygen*len(l['groups'])*l['replicates']
    sources=c['screen_candidates_per_alpha']*len(p['alphas'])
    native_cases+=sources*c['screen_replicates']*(c['screen_passages']+oxygen*len(c['minority_probe_fractions']))+c['finalists']*c['final_replicates']*(episodes+oxygen*len(c['minority_probe_fractions']))
    fit_attempts=l['shared_starts']+l['ridge_starts_per_alpha']*len(l['alphas'])+p['starts_per_alpha']*len(p['alphas'])+sources*c['refinement_replicates']
    frame_assets=(l['native_pool']['shared']+l['native_pool']['ridge_per_alpha']*len(l['alphas'])+sources+c['finalists'])*len(s['figure_rows'])*len(s['figure_replicates'])
    durable_parts={key:s[key] for key in ['compact_measurement_reservation_bytes','figure_reservation_bytes','fit_logs_reservation_bytes','cache_peak_reservation_bytes','report_reservation_bytes','metadata_reservation_bytes']}
    errors=[]
    interrupted_extra=slots*max(0,s['compact_case_total_bytes']-s['compact_case_final_bytes'])
    if native_cases*s['compact_case_final_bytes']+interrupted_extra>s['compact_measurement_reservation_bytes']:errors.append('Configured native task count exceeds compact durable reservation')
    if s['compact_case_final_bytes']<5*s['compact_case_bytes']+65536:errors.append('Final compact closed-list bound is too small')
    if s['compact_case_total_bytes']>s['case_components_bytes']['other']:errors.append('Active compact atomic overlap exceeds case reservation')
    if fit_attempts*s['fit_attempt_max_bytes']>s['fit_logs_reservation_bytes']:errors.append('Configured fit/refinement task count exceeds bounded fit reservation')
    if frame_assets*s['frame_bytes']>s['figure_staging_reservation_bytes']:errors.append('Recognized candidate fields exceed figure reservation before pruning')
    if sum(durable_parts.values())>s['new_durable_bytes_reservation']:errors.append('All durable components exceed new run reservation')
    if s.get('jit_disk_cache',False):errors.append('Persistent JIT caches require an explicit bounded implementation; this profile keeps code in memory')
    if durable>50*GB or transient>100*GB or min(durable,transient,slots,case)<=0:errors.append('Storage limits exceed the project policy or are nonpositive')
    if estimated>durable:errors.append('Estimated existing plus new durable bytes exceed durable limit')
    if durable+slots*case+s['figure_staging_reservation_bytes']>transient:errors.append('Durable ceiling plus all simultaneous native reservations exceeds total peak limit')
    if slots>r['max_concurrent_cpus']:errors.append('Native reservations exceed the CPU envelope')
    if s['frame_max_cells']!=200000 or s['frame_fields']!=5 or s['frame_bytes']<64+200000*5*8:errors.append('Compact frame bound differs from the engine protocol')
    components=s['case_components_bytes']
    if sum(components.values())>case:errors.append('Case component reservations exceed per-case reservation')
    if components.get('frame_and_atomic_overlap',0)<2*s['frame_bytes']:errors.append('Atomic frame overlap is not reserved')
    if s['report_reservation_bytes']+s['figure_reservation_bytes']>s['new_durable_bytes_reservation']:errors.append('Report/figure reservations exceed durable run reservation')
    return {'valid':not errors,'errors':errors,'accounting_units':'decimal bytes; GB=1e9; copies count independently','existing_estimate_bytes':s['existing_project_bytes_estimate'],'new_durable_reserved_bytes':s['new_durable_bytes_reservation'],'durable_ceiling_bytes':durable,'native_case_slots':slots,'native_case_count':native_cases,'native_compact_durable_bytes':native_cases*s['compact_case_final_bytes'],'native_compact_case_active_bytes':s['compact_case_total_bytes'],'interrupted_compact_extra_reserved_bytes':interrupted_extra,'fit_attempt_count':fit_attempts,'maximum_field_assets':frame_assets,'durable_components':durable_parts,'native_reserved_bytes':slots*case,'candidate_field_staging_bytes':s['figure_staging_reservation_bytes'],'peak_reserved_bytes':durable+slots*case+s['figure_staging_reservation_bytes'],'total_peak_limit_bytes':transient,'peak_native_inodes':slots*s['case_inode_limit'],'durable_inode_reservation':s['durable_inode_reservation'],'scope':'All project-created files, caches, local/shared/node scratch and independent copies; symlinks do not exempt their targets','runtime_inventory_required':True,'raw_retention':'None; measure each acknowledged frame and unlink immediately; bounded compact recognized figure fields only'}


def inventory(roots,read_only_external_roots=()):
    """Count unique files by device/inode; copied files remain distinct.

    Resolve symlinks, refusing undeclared external targets unless explicitly
    identified as existing read-only input/environment roots.
    """
    roots=[Path(p).resolve() for p in roots];readonly=[Path(p).resolve() for p in read_only_external_roots]
    seen=set();pending=list(roots);result={'bytes':0,'allocated_bytes':0,'files':0,'directories':0,'symlinks':0,'dangling_symlinks':[],'excluded_read_only_targets':[],'roots':[str(p) for p in roots],'read_only_external_roots':[str(p) for p in readonly],'inventory_unix':time.time()}
    def inside(path,base):
        try:path.relative_to(base);return True
        except ValueError:return False
    while pending:
        path=pending.pop();st=path.lstat();key=(st.st_dev,st.st_ino)
        if key in seen:continue
        seen.add(key)
        if path.is_symlink():
            result['symlinks']+=1;result['bytes']+=st.st_blocks*512;result['allocated_bytes']+=st.st_blocks*512;target=path.resolve()
            if not target.exists():result['dangling_symlinks'].append({'path':str(path),'target':str(target),'target_bytes':0})
            elif any(inside(target,b) for b in roots):pending.append(target)
            elif any(inside(target,b) for b in readonly):result['excluded_read_only_targets'].append(str(target))
            else:raise ValueError('Uninventoried external project target: '+str(path)+' -> '+str(target))
        elif path.is_dir():
            result['directories']+=1;result['bytes']+=st.st_blocks*512;result['allocated_bytes']+=st.st_blocks*512;pending.extend(path.iterdir())
        elif path.is_file():
            result['files']+=1;result['bytes']+=max(st.st_size,st.st_blocks*512);result['allocated_bytes']+=st.st_blocks*512
    result['inventory_sha256']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
    return result


def initialize(run,config,inventory_record):
    run=Path(run);s=config['storage'];plan=storage_plan(config)
    if not plan['valid']:raise ValueError('; '.join(plan['errors']))
    if inventory_record['bytes']+s['new_durable_bytes_reservation']>s['durable_limit_bytes']:raise ValueError('Actual project footprint leaves insufficient durable run/report headroom')
    record={'inventory':inventory_record,'plan':plan,'native_active':{},'initialized_unix':time.time()}
    write(run/'storage/state.json',record);write(run/'storage/plan.json',plan)
    return record


@contextmanager
def reserve_case(run,config,key,directory):
    """Reserve before export; release only after all transient bytes are removed."""
    run=Path(run);directory=Path(directory);s=config['storage'];root=run/'transient'
    root.mkdir(exist_ok=True)
    if directory.parent.resolve()!=root.resolve():raise ValueError('Transient native case must use the declared run transient root')
    lock=run/'storage/reservations.lock';lock.parent.mkdir(exist_ok=True)
    with lock.open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        state=json.loads((run/'storage/state.json').read_text())
        if key in state['native_active']:raise ValueError('Native disk reservation already active: '+key)
        if len(state['native_active'])>=s['native_case_slots']:raise ValueError('Native disk reservation slots exhausted; no simulation started')
        state['native_active'][key]={'directory':str(directory),'reserved_bytes':s['case_reservation_bytes'],'job_id':os.environ.get('SLURM_JOB_ID'),'pid':os.getpid(),'start_unix':time.time()}
        write(run/'storage/state.json',state)
    failed=True
    try:
        lease={'completion_verified':True,'case_bytes':s['case_reservation_bytes'],'case_inodes':s['case_inode_limit'],'frame_bytes':s['frame_bytes'],'input_bytes':s['case_components_bytes']['initial_inputs'],'log_bytes':s['case_components_bytes']['logs'],'compact_bytes':s['compact_case_bytes'],'protocol_required':True}
        yield lease
        failed=not lease['completion_verified']
    finally:
        # No copy/retention exception: compact measurements live outside this tree.
        if directory.exists():shutil.rmtree(directory)
        with lock.open('a+') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX)
            state=json.loads((run/'storage/state.json').read_text())
            if failed:
                state['native_active'][key].update(cleaned_transient=True,compact_finalization_unverified=True)
            else:state['native_active'].pop(key,None)
            write(run/'storage/state.json',state)


def cleanup_transient(run):
    """Controller-only after terminating/reaping own workers, including SIGKILL."""
    run=Path(run);root=run/'transient';removed=0
    if root.exists():
        for path in root.iterdir():
            if path.is_dir() and not path.is_symlink():shutil.rmtree(path)
            else:path.unlink()
            removed+=1
    return {'removed_transient_cases':removed,'raw_native_retained':False}


def asset_callbacks(run,config):
    """Bound full-precision recognized fields independently of transient space."""
    run=Path(run).resolve();limit=config['storage']['figure_staging_reservation_bytes']
    def reserve(size,path,provenance):
        path=Path(path).resolve()
        try:relative=path.relative_to(run)
        except ValueError:raise ValueError('Field asset outside current run')
        if relative.parts[0]=='transient' or size>config['storage']['frame_bytes']:raise ValueError('Invalid durable field asset')
        token=hashlib.sha256(str(relative).encode()).hexdigest()
        with (run/'storage/reservations.lock').open('a+') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX);state=json.loads((run/'storage/state.json').read_text());assets=state.setdefault('field_assets',{})
            if token in assets:raise ValueError('Duplicate field asset reservation')
            if sum(v['bytes'] for v in assets.values())+size>limit:return False
            assets[token]={'path':str(path),'relative_path':str(relative),'bytes':size,'status':'reserved','provenance':provenance};write(run/'storage/state.json',state)
        return token
    def commit(token,record):
        with (run/'storage/reservations.lock').open('a+') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX);state=json.loads((run/'storage/state.json').read_text());asset=state['field_assets'][token]
            if Path(asset['path']).stat().st_size>asset['bytes']:raise ValueError('Field asset exceeds reservation')
            asset.update(status='committed',record=record);write(run/'storage/state.json',state)
    def release(token):
        if not token:return
        with (run/'storage/reservations.lock').open('a+') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX);state=json.loads((run/'storage/state.json').read_text());state.setdefault('field_assets',{}).pop(token,None);write(run/'storage/state.json',state)
    return reserve,commit,release


def cleanup_unretained_assets(run,retained_paths):
    """After quiescence, close owned field leases even if a manifest write crashed."""
    import re
    run=Path(run).resolve();retained={str(Path(name)) for name in retained_paths}
    removed=[]
    with (run/'storage/reservations.lock').open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX);state=json.loads((run/'storage/state.json').read_text())
        assets=state.setdefault('field_assets',{})
        for token,asset in list(assets.items()):
            relative=asset['relative_path']
            if relative in retained:continue
            path=run/relative
            if path.resolve()!=Path(asset['path']) or run not in path.resolve().parents or path.is_symlink() or not re.fullmatch(r'field_frame_[0-9]{4}\.bin',path.name):raise ValueError('Unrecognized orphan field lease')
            record=asset.get('record',{})
            if path.exists():
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                if path.stat().st_size>asset['bytes'] or record.get('sha256',digest)!=digest:raise ValueError('Orphan field differs from its reservation')
                path.unlink();removed.append({'path':relative,'sha256':digest,'bytes':asset['bytes'],'prior_status':asset['status']})
            assets.pop(token)
        write(run/'storage/state.json',state)
    result={'removed':removed,'retained_paths':sorted(retained),'quiescent_only':True,'numeric_evidence_removed':False}
    write(run/'storage/orphan_field_cleanup.json',result);return result


def frozen_inventory(path,digest,roots,readonly,max_age_seconds=600,clock=time.time):
    """Reuse one explicit, hash-bound post-cleanup measurement during launch freeze."""
    path=Path(path);blob=path.read_bytes()
    if not digest or hashlib.sha256(blob).hexdigest()!=digest:raise ValueError('Project inventory snapshot hash mismatch')
    value=json.loads(blob);age=clock()-value.get('inventory_unix',0)
    if not 0<=age<=min(600,max_age_seconds):raise ValueError('Project inventory snapshot is stale or future dated')
    if value.get('roots')!=[str(Path(p).resolve()) for p in roots] or value.get('read_only_external_roots',[])!=[str(Path(p).resolve()) for p in readonly]:raise ValueError('Project inventory ownership roots differ from snapshot')
    value.update(verified=True,snapshot_sha256=digest,snapshot_path=str(path),snapshot_age_seconds=age)
    return value
