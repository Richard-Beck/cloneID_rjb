"""Bounded output-only native frame/ACK protocol; no XML/MAT fallback.

Each audited engine publishes at most one 64+200000*5*8-byte frame, then waits
for ACK. The observer persists only its 30 values, numeric state CSV, small
provenance and optionally whitelisted thumbnails before deleting/ACKing it.
RLIMIT_FSIZE/CORE and byte/inode monitoring are additional guards, not the
proof of aggregate storage bounds. A killed Python process needs the run janitor.
"""
from pathlib import Path
import csv
import hashlib
import io
import json
import math
import os
import resource
import re
import selectors
import shutil
import signal
import struct
import subprocess
import threading
import time
import numpy as np

PROTOCOL='cloneid-native-frame'
VERSION=1
MAX_CELLS=200000
MAX_SAMPLES=1024
HEADER=struct.Struct('<8sIIQdQQQQ')
MAX_FRAME_BYTES=8000064
HANDSHAKE='CLONEID_NATIVE_FRAME_PROTOCOL 1 200000 5 8000064\n'
STORAGE_CONTEXT=None
COMPACT_TOTAL_BYTES=2000000
COMPACT_FILE_BYTES=262144
LOG_BYTES=65536
TRAJECTORY_BYTES=262144
CLOSED_FILES={"observables.npz","outcome.json","stream_identity.json","state_trajectory.csv","field_assets.json","stream_observables.npz","stream_provenance.json","engine.log"}
DEFAULTS=dict(case_bytes=32*1024**2,case_inodes=64,file_bytes=MAX_FRAME_BYTES,
              initial_bytes=4*1024**2,initial_inodes=16,compact_bytes=COMPACT_FILE_BYTES,
              trajectory_bytes=TRAJECTORY_BYTES,log_bytes=LOG_BYTES,figure_bytes=128*1024,
              poll_seconds=.02,handshake_seconds=5.,capability_seconds=5.)


def _clean(value):
    if isinstance(value,Path):return str(value)
    if isinstance(value,dict):return {str(k):_clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list,np.ndarray)):return [_clean(v) for v in value]
    if isinstance(value,np.integer):return int(value)
    if isinstance(value,(float,np.floating)):return float(value) if math.isfinite(value) else None
    return value


def context(directory,limits=None):
    raw=STORAGE_CONTEXT(directory) if callable(STORAGE_CONTEXT) else STORAGE_CONTEXT or {}
    result=dict(DEFAULTS);result.update(raw.get('limits',{}));result.update({k:v for k,v in raw.items() if k!='limits'});result.update(limits or {})
    if 'input_bytes' in result:result['initial_bytes']=result['input_bytes']
    if 'frame_bytes' in result:result['file_bytes']=result['frame_bytes']
    result['compact_bytes']=min(result['compact_bytes'],COMPACT_FILE_BYTES)
    result['trajectory_bytes']=min(result['trajectory_bytes'],TRAJECTORY_BYTES)
    result['log_bytes']=min(result['log_bytes'],LOG_BYTES)
    for key in ('case_bytes','case_inodes','file_bytes','initial_bytes','initial_inodes','compact_bytes','trajectory_bytes','log_bytes','figure_bytes'):
        if not isinstance(result[key],int) or isinstance(result[key],bool) or result[key]<=0:raise ValueError('Invalid native storage limit: '+key)
    if result['file_bytes']<MAX_FRAME_BYTES:raise ValueError('Native file cap must admit the exact 8000064-byte bounded frame')
    if result['case_bytes']<MAX_FRAME_BYTES+result['initial_bytes']+result['trajectory_bytes']:raise ValueError('Native case reservation cannot hold bounded frame and declared inputs/trajectory')
    if not 0<result['poll_seconds']<=1:raise ValueError('Invalid native polling interval')
    return result



def case_directory(compact_parent,default=None):
    raw=STORAGE_CONTEXT(compact_parent) if callable(STORAGE_CONTEXT) else STORAGE_CONTEXT or {}
    chosen=raw.get('case_directory',raw.get('transient_directory',default or Path(compact_parent)/'case'))
    return Path(chosen(compact_parent) if callable(chosen) else chosen)


def write_initial_csv(frame,path):
    """Check the complete deterministic CSV bytes before creating its file."""
    path=Path(path);cfg=context(path.parent);data=frame.to_csv(index=False).encode()
    limit=cfg['initial_bytes']-256*1024
    if limit<=0:raise ValueError('Insufficient native initial-input reservation')
    _atomic(path,data,limit)


def compact_contract():
    return dict(per_file_bytes=COMPACT_FILE_BYTES,log_bytes=LOG_BYTES,state_bytes=TRAJECTORY_BYTES,
                final_files=['observables.npz','outcome.json','stream_identity.json','state_trajectory.csv','field_assets.json','engine.log'],
                transitional_files=['stream_observables.npz','stream_provenance.json'],
                final_closed_list_max_bytes=5*COMPACT_FILE_BYTES+LOG_BYTES,
                retained_with_transitional_files_max_bytes=7*COMPACT_FILE_BYTES+LOG_BYTES,
                aggregate_including_atomic_temporaries_max_bytes=COMPACT_TOTAL_BYTES,
                field_payloads='Only globally reserved field_frame_NNNN.bin excluded; field_assets.json metadata is counted',
                atomic_admission='Count existing destination and temporary simultaneously; reject before writing if total would exceed 2000000 bytes')


def compact_usage(directory):
    total=0
    for path in Path(directory).iterdir():
        if path.is_file() and not re.fullmatch(r'field_frame_[0-9]{4}\.bin',path.name):total+=path.stat().st_size
    return total


def write_json(path,value):
    _json(path,value,COMPACT_FILE_BYTES)


def write_npz(path,**values):
    output=io.BytesIO();np.savez_compressed(output,**values);_atomic(path,output.getvalue(),COMPACT_FILE_BYTES)



def map_observables(directory,indices,lookup):
    """Map a just-measured immutable stream to frozen observation rows."""
    directory=Path(directory);indices=np.asarray(indices,int);lookup=np.asarray(lookup,int)
    with np.load(directory/'stream_observables.npz',allow_pickle=False) as saved:
        available=saved['requested_time_support'];mask=available[lookup]
        write_npz(directory/'observables.npz',indices=indices[mask],predicted=saved['predicted'][lookup[mask]],trajectory_predicted=saved['predicted'],times_minutes=saved['times_minutes'],actual_times_minutes=saved['actual_times_minutes'],requested_indices=indices,requested_time_support=available,frame_sha256=saved['frame_sha256'],stream_identity_sha256=saved['stream_identity_sha256'],protocol_version=saved['protocol_version'])
    return int(mask.sum())


def write_state_csv(path,frame):_atomic(path,frame.to_csv(index=False).encode(),TRAJECTORY_BYTES)


def run_expectation(run,candidate_id,source_sha256,stage,replicate):
    run=Path(run);identity=json.loads((run/'run_identity.json').read_text())
    return dict(run_id=identity['run_id'],input_manifest_sha256=hashlib.sha256((run/'input_manifest.json').read_bytes()).hexdigest(),candidate_id=candidate_id,source_checkpoint_sha256=source_sha256,stage=stage,replicate=int(replicate))

def finalize_compact_case(directory):
    directory=Path(directory)
    if not (directory/'outcome.json').exists():raise ValueError('Cannot remove compact progress before outcome is durable')
    for name in ['stream_observables.npz','stream_provenance.json']:
        (directory/name).unlink(missing_ok=True)
    for path in directory.glob('*.part'):
        if path.name[:-5] in CLOSED_FILES:path.unlink()
    if compact_usage(directory)>compact_contract()['final_closed_list_max_bytes']:raise ValueError('Final compact case exceeds closed-list budget')
    if isinstance(STORAGE_CONTEXT,dict):STORAGE_CONTEXT['_compact_finalized']=True

def _atomic(path,data,limit):
    path=Path(path)
    if len(data)>limit:raise ValueError('Compact native artifact exceeds declared byte cap: '+path.name)
    path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_name(path.name+'.part')
    if path.name in CLOSED_FILES:
        temporary.unlink(missing_ok=True)
        if compact_usage(path.parent)+len(data)>COMPACT_TOTAL_BYTES:raise ValueError('Aggregate compact native case would exceed 2000000 bytes')
    with temporary.open('wb') as stream:stream.write(data)
    temporary.replace(path)


def _json(path,value,limit):_atomic(path,(json.dumps(_clean(value),separators=(',',':'),allow_nan=False)+'\n').encode(),limit)


def _usage(directory):
    total=0;inodes=0
    if not Path(directory).exists():return total,inodes
    for root,dirs,files in os.walk(directory,followlinks=False):
        inodes+=1
        for name in files:
            try:total+=(Path(root)/name).lstat().st_size;inodes+=1
            except FileNotFoundError:pass
    return total,inodes


def _kill(process):
    if process is None:return
    # Kill the complete engine process group, including an ACK-blocked child.
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:process.wait(timeout=1.)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=2.)


def _child_limits(limit):
    def apply():
        resource.setrlimit(resource.RLIMIT_FSIZE,(limit,limit))
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE);cap=min(64,hard) if hard!=resource.RLIM_INFINITY else 64
        resource.setrlimit(resource.RLIMIT_NOFILE,(cap,cap))
    return apply


def engine_capability(executable,timeout=5.,popen=subprocess.Popen):
    """An output-only CLI probe; old engines fail before any case/model run."""
    process=None;selector=None;data=bytearray()
    try:
        process=popen([str(executable),'--cloneid-frame-protocol'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                      stdin=subprocess.DEVNULL,start_new_session=True,preexec_fn=_child_limits(MAX_FRAME_BYTES),env={**os.environ,'CLONEID_NATIVE_FRAME_PROTOCOL':''})
        selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ);deadline=time.monotonic()+timeout
        while selector.get_map():
            if time.monotonic()>deadline:raise RuntimeError('Native compact-frame capability probe timed out')
            for key,_ in selector.select(.02):
                chunk=os.read(key.fd,4096)
                if not chunk:selector.unregister(key.fileobj);continue
                data.extend(chunk)
                if len(data)>4096:raise RuntimeError('Unbounded native capability response')
        process.wait(timeout=max(.01,deadline-time.monotonic()))
        lines=data.decode(errors='replace').strip().splitlines();value=json.loads(lines[-1]) if lines else {}
        if process.returncode or value.get('protocol')!=PROTOCOL or value.get('version')!=1 or value.get('fields')!=5 or value.get('max_cells')!=MAX_CELLS or value.get('max_frame_bytes')!=MAX_FRAME_BYTES or value.get('acknowledged') is not True:
            raise RuntimeError('Engine lacks required compact frame/ACK protocol v1; rebuild both canonical runtimes; XML/MAT fallback is forbidden')
        return value
    except (ValueError,KeyError,IndexError,json.JSONDecodeError) as error:
        raise RuntimeError('Engine lacks required compact frame/ACK protocol v1; XML/MAT fallback is forbidden') from error
    finally:
        _kill(process)
        if selector is not None:selector.close()
        if process is not None and process.stdout is not None:process.stdout.close()


def read_frame(path):
    path=Path(path);size=path.stat().st_size
    if size<HEADER.size or size>MAX_FRAME_BYTES:raise ValueError('Native frame size violates protocol bound')
    raw=path.read_bytes();magic,version,fields,index,minutes,number,payload,events,reserved=HEADER.unpack_from(raw)
    if magic!=b'CLIDFRM1' or version!=1 or fields!=5 or number>MAX_CELLS or payload!=number*40 or size!=64+payload or reserved!=0 or not math.isfinite(minutes):raise ValueError('Invalid/incomplete compact native frame header/payload')
    values=np.frombuffer(raw,offset=64,dtype='<f8').reshape(number,5)
    if not np.isfinite(values).all() or not np.isin(values[:,3],[0.,1.]).all() or not np.isin(values[:,4],[0.,1.]).all():raise ValueError('Invalid compact native cell values')
    return dict(index=int(index),actual_minutes=float(minutes),cells=int(number),x=values[:,0],y=values[:,1],total_volume=values[:,2],dead=values[:,3],cell_type=values[:,4],wgd_events=int(events),frame_sha256=hashlib.sha256(raw).hexdigest(),frame_bytes=size)


def _trajectory(directory,dest,limit):
    source=Path(directory)/'state_trajectory.csv'
    if not source.exists():return
    if source.stat().st_size>limit:raise ValueError('Native numeric trajectory exceeds declared byte cap')
    raw=source.read_bytes();end=raw.rfind(b'\n')
    if end<0:return
    complete=raw[:end+1];rows=list(csv.reader(io.StringIO(complete.decode())))
    if not rows:return
    if len(rows)>MAX_SAMPLES+1:raise ValueError('Native numeric trajectory exceeds bounded sample count')
    width=len(rows[0])
    for row in rows[1:]:
        if len(row)!=width:raise ValueError('Incomplete native numeric trajectory row')
        for item in row:float(item)
    _atomic(dest,complete,limit)


def _frame_state(frame):
    low=frame['cell_type']!=1;high=~low;dead=frame['dead']!=0
    return [frame['actual_minutes'],int(np.sum(low&~dead)),int(np.sum(high&~dead)),int(np.sum(low&dead)),int(np.sum(high&dead)),frame['wgd_events']]


def execute(command,directory,times,measure_callback,timeout,*,compact_directory=None,measure=True,env=None,limits=None,provenance=None,figure_requests=None,figure_geometry=None,popen=subprocess.Popen):
    """Run an ACK-capable engine; compact results survive failure/cancellation.

    measure_callback(frame_dict)->(float64[30],metadata), using the unchanged
    geometry observer. STORAGE_CONTEXT may be dict or callable(case_path)->dict.
    Case inputs are pre-exported. All files below directory are removed in finally.
    """
    directory=Path(directory).resolve();compact=Path(compact_directory or directory.parent).resolve()
    if compact==directory or directory in compact.parents:raise ValueError('Compact output must be outside the deleted native case')
    cfg=context(directory,limits);times=np.asarray(times,float)
    if times.ndim!=1 or not 0<len(times)<=MAX_SAMPLES or not np.isfinite(times).all() or np.any(np.diff(times)<0):raise ValueError('Invalid bounded native sample times')
    compact.mkdir(parents=True,exist_ok=True);values=np.full((len(times),30),np.nan);available=np.zeros(len(times),bool);actual_times=np.full(len(times),np.nan);frame_hashes=np.full(len(times),b'',dtype='S64');identity_sha256='';records=[dict(requested_minutes=float(t),status='missing') for t in times];assets=[];states=[]
    metadata=dict(cfg.get('provenance',{}));metadata.update(provenance or {})
    if figure_geometry is not None:
        geometry=dict(figure_geometry) if isinstance(figure_geometry,dict) else dict(zip(['domain_size','field_shape','crop_origin'],figure_geometry))
        geometry.setdefault('units',dict(position='pixels',total_volume='pixels^3',projected_area='pixels^2',time='minutes'))
        metadata['geometry']=_clean(geometry)
    if 'case_spec' in metadata:metadata['case_spec_sha256']=hashlib.sha256(json.dumps(_clean(metadata['case_spec']),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    for key in ['run_id','input_manifest_sha256','run_root']:
        if key in cfg:metadata.setdefault(key,cfg[key])
    process=None;started=time.monotonic();engine_started=None;engine_finished=None;observer_seconds=0.;log_tail=bytearray();log_total=0;log_thread=None;cancel=threading.Event();old_handlers={};last_index=-1
    result=dict(status='failure',engine_status='not_started',protocol=PROTOCOL,protocol_version=1,raw_fields_retained=False,storage_limits={key:cfg[key] for key in DEFAULTS},bound_method='Audited <=200000-cell single-frame ACK protocol (8000064 bytes), <=1024 requested samples, bounded initial CSV/trajectory/log/compact artifacts; limits and filesystem monitor add defense in depth.',peak_case_bytes=0,peak_case_inodes=0)
    def log_reader():
        nonlocal log_total
        while True:
            chunk=os.read(process.stdout.fileno(),8192)
            if not chunk:break
            log_total+=len(chunk);log_tail.extend(chunk)
            if len(log_tail)>cfg['log_bytes']:del log_tail[:-cfg['log_bytes']]
    def save_numeric():
        write_npz(compact/'stream_observables.npz',times_minutes=times,actual_times_minutes=actual_times,predicted=values,requested_time_support=available,frame_sha256=frame_hashes,stream_identity_sha256=np.array(identity_sha256),protocol_version=np.array(1))
    def check_usage():
        size,count=_usage(directory);result['peak_case_bytes']=max(result['peak_case_bytes'],size);result['peak_case_inodes']=max(result['peak_case_inodes'],count)
        if size>cfg['case_bytes'] or count>cfg['case_inodes']:raise RuntimeError('Audited native case storage byte/inode bound violated')
        if any(directory.rglob('*.mat')) or any(directory.rglob('*.xml')) and any(path.name!='PhysiCell_settings.xml' for path in directory.rglob('*.xml')):raise RuntimeError('Forbidden XML/MAT output: compact protocol is mandatory')
    def request_cancel(signum,frame):cancel.set();result['cancel_signal']=int(signum)
    try:
        size,count=_usage(directory)
        if size>cfg['initial_bytes'] or count>cfg['initial_inodes']:raise RuntimeError('Native initial case exceeds reserved input bytes/inodes')
        _json(compact/'stream_identity.json',dict(protocol=PROTOCOL,protocol_version=1,times_minutes=times.tolist(),provenance=metadata,input_artifact_sha256={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.iterdir() if path.is_file()}),cfg['compact_bytes'])
        identity_sha256=hashlib.sha256((compact/'stream_identity.json').read_bytes()).hexdigest()
        result['stream_identity_sha256']=identity_sha256
        result['capability']=engine_capability(command[0],cfg['capability_seconds'],popen=popen)
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM,signal.SIGINT):old_handlers[sig]=signal.getsignal(sig);signal.signal(sig,request_cancel)
        process=popen([str(v) for v in command],cwd=directory,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True,preexec_fn=_child_limits(min(cfg['file_bytes'],MAX_FRAME_BYTES)),env={**os.environ,**(env or {}),'CLONEID_NATIVE_FRAME_PROTOCOL':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
        engine_started=time.monotonic()
        result['engine_status']='running';log_thread=threading.Thread(target=log_reader,daemon=True);log_thread.start();handshake_deadline=time.monotonic()+cfg['handshake_seconds'];handshake=False
        while True:
            if cancel.is_set():result.update(engine_status='cancelled',error='Native engine cancelled');break
            if time.monotonic()-(engine_started or started)-observer_seconds>timeout:result.update(engine_status='timed_out',error='Native engine active-time timeout');break
            check_usage()
            if not handshake:
                path=directory/'stream.protocol'
                if path.exists() and path.read_text()==HANDSHAKE:handshake=True;result['runtime_handshake']=True
                elif time.monotonic()>handshake_deadline:raise RuntimeError('Missing required native compact protocol handshake; no XML/MAT fallback')
            ready=directory/'stream.frame.ready'
            if ready.exists():
                frame=read_frame(ready);index=frame['index']
                if not handshake or index!=last_index+1 or index>=len(times) or abs(frame['actual_minutes']-times[index])>.500001:raise ValueError('Native compact frame identity/order/time mismatch')
                record=dict(requested_minutes=float(times[index]),actual_minutes=frame['actual_minutes'],status='state_only' if not measure else 'measurement_failed',frame_sha256=frame['frame_sha256'],frame_bytes=frame['frame_bytes'],cells=frame['cells'],wgd_events=frame['wgd_events'])
                actual_times[index]=frame['actual_minutes'];frame_hashes[index]=frame['frame_sha256'].encode()
                states.append(_frame_state(frame));_trajectory(directory,compact/'state_trajectory.csv',cfg['trajectory_bytes'])
                if not (directory/'state_trajectory.csv').exists():
                    output=io.StringIO();writer=csv.writer(output);writer.writerow(['time_minutes','n_low','n_high','n_dead_low','n_dead_high','wgd_events']);writer.writerows(states);_atomic(compact/'state_trajectory.csv',output.getvalue().encode(),cfg['trajectory_bytes'])
                before=time.monotonic()
                try:
                    if measure:
                        value,extra=measure_callback(frame);value=np.asarray(value,float)
                        if value.shape!=(30,):raise ValueError('Expected 30 compact native observables')
                        values[index]=value;record.update(status='measured',metadata=extra,finite_components=int(np.isfinite(value).sum()))
                    available[index]=True
                    requests=sorted(set(int(row) for row in (figure_requests or {}).get(index,[]) if int(row) in {175,57,342,234}))
                    required=['run_root','run_id','input_manifest_sha256','candidate_id','source_checkpoint_sha256','geometry','seed','case_spec_sha256']
                    if requests:
                        if metadata.get('replicate')!=0:record['asset_retention']='unavailable_nonzero_or_missing_replicate'
                        elif not all(metadata.get(key) is not None for key in required) or metadata.get('case_index',metadata.get('slot_index')) is None:record['asset_retention']='unavailable_missing_immutable_provenance'
                        elif not callable(cfg.get('reserve_asset')):record['asset_retention']='unavailable_global_asset_reservation'
                        else:
                            target=compact/f'field_frame_{index:04}.bin';size=frame['frame_bytes'];token=cfg['reserve_asset'](size,target,metadata)
                            if token is False or token is None:record['asset_retention']='global_asset_budget_exhausted'
                            else:
                                try:
                                    # Same-run transient/durable roots must share a filesystem.
                                    # Rename retains exact bytes without a second frame copy.
                                    ready.replace(target)
                                    asset={key:metadata[key] for key in ['run_id','input_manifest_sha256','candidate_id','source_checkpoint_sha256']}|dict(path=str(target.relative_to(Path(metadata['run_root']).resolve())),sha256=frame['frame_sha256'],bytes=size,kind='native_cell_frame_v1',protocol_version=1,required_for_report=True,observation_row=requests[0],observation_rows=requests,replicate=0,stage=metadata.get('stage'),sample_index=index,actual_minutes=frame['actual_minutes'],requested_minutes=float(times[index]),geometry=metadata.get('geometry'),seed=metadata.get('seed'),case_index=metadata.get('case_index',metadata.get('slot_index')),case_spec_sha256=metadata.get('case_spec_sha256'))
                                    if callable(cfg.get('commit_asset')):cfg['commit_asset'](token,asset)
                                    assets.append(asset);record['asset_retention']='retained_exact_compact_frame'
                                except BaseException:
                                    if target.exists():target.unlink()
                                    if callable(cfg.get('release_asset')):cfg['release_asset'](token)
                                    raise

                except Exception as error:record['error']=repr(error)
                observer_seconds+=time.monotonic()-before;records[index]=record;save_numeric();last_index=index
                _json(compact/'field_assets.json',dict(assets=assets,raw_fields_retained=False),cfg['compact_bytes'])
                ready.unlink(missing_ok=True)
                # Drop every reference to cell payload before the engine may advance.
                del frame
                if cancel.is_set():result.update(engine_status='cancelled',error='Native engine cancelled');break
                _atomic(directory/'stream.ack',(str(index)+'\n').encode(),64)
            if process.poll() is not None and not ready.exists():
                result['engine_returncode']=process.returncode;result['engine_status']='complete' if process.returncode==0 else 'failed'
                if process.returncode:result['error']=f'Engine returncode {process.returncode}'
                break
            time.sleep(cfg['poll_seconds'])
        if result['engine_status']=='complete' and (not handshake or last_index!=len(times)-1):result.update(engine_status='failed',error='Native compact engine exited before all requested frames')
    except Exception as error:result.update(engine_status='failed',error=f'{type(error).__name__}: {error}')
    finally:
        _kill(process)
        engine_finished=time.monotonic()
        if log_thread is not None:log_thread.join(timeout=2.)
        if process is not None and process.stdout is not None:process.stdout.close()
        for sig,handler in old_handlers.items():signal.signal(sig,handler)
        try:_trajectory(directory,compact/'state_trajectory.csv',cfg['trajectory_bytes'])
        except Exception as error:result['trajectory_error']=repr(error)
        try:save_numeric();_atomic(compact/'engine.log',bytes(log_tail),cfg['log_bytes'])
        except Exception as error:result['compact_write_error']=repr(error)
        try:
            check_usage()
        except Exception as error:result['storage_guard_error']=repr(error)
        try:shutil.rmtree(directory);result['case_cleanup_complete']=True
        except FileNotFoundError:result['case_cleanup_complete']=True
        except OSError as error:result.update(case_cleanup_complete=False,cleanup_error=repr(error))
        result.update(wall_seconds=time.monotonic()-started,observer_seconds=observer_seconds,engine_seconds=max(0.,engine_finished-engine_started-observer_seconds) if engine_started is not None else 0.,requested_snapshots=len(times),measured_snapshots=int(available.sum()),snapshots=records,log_bytes_seen=log_total,log_bytes_retained=len(log_tail),log_truncated=log_total>len(log_tail),compact_observables='stream_observables.npz',state_trajectory='state_trajectory.csv' if (compact/'state_trajectory.csv').exists() else None)
        complete=result['engine_status']=='complete' and bool(available.all()) and (not measure or bool(np.isfinite(values).all()))
        result['status']='success' if complete else 'partial' if available.any() else 'failure'
        _json(compact/'stream_provenance.json',dict(result,provenance=metadata),cfg['compact_bytes'])
    result.update(predicted=values,requested_time_support=available)
    return result


def load_compact_evidence(directory,expected,times):
    """Strict source-bound recovery reader; no engine or model evaluation."""
    directory=Path(directory);identity_path=directory/'stream_identity.json'
    if not identity_path.exists():return None
    if identity_path.stat().st_size>COMPACT_FILE_BYTES:raise ValueError('Oversized compact recovery identity')
    identity=json.loads(identity_path.read_text())
    if identity.get('protocol')!=PROTOCOL or identity.get('protocol_version')!=1:raise ValueError('Compact recovery protocol mismatch')
    required=['run_id','input_manifest_sha256','candidate_id','source_checkpoint_sha256','stage','replicate']
    provenance=identity.get('provenance',{})
    if any(key not in expected or key not in provenance or provenance[key]!=expected[key] for key in required):raise ValueError('Compact recovery source/run/candidate identity mismatch')
    times=np.asarray(times,float)
    if not np.array_equal(np.asarray(identity.get('times_minutes'),float),times):raise ValueError('Compact recovery frozen requested times mismatch')
    path=directory/'stream_observables.npz'
    if not path.exists():path=directory/'observables.npz'
    if not path.exists():return None
    if path.stat().st_size>COMPACT_FILE_BYTES:raise ValueError('Oversized compact recovery NPZ')
    with np.load(path,allow_pickle=False) as saved:
        needed=['protocol_version','stream_identity_sha256','times_minutes','actual_times_minutes','requested_time_support','frame_sha256']
        if any(key not in saved for key in needed):raise ValueError('Compact recovery NPZ lacks protocol/source metadata')
        if int(saved['protocol_version'])!=1 or str(saved['stream_identity_sha256'])!=hashlib.sha256(identity_path.read_bytes()).hexdigest():raise ValueError('Compact recovery identity hash/protocol mismatch')
        if saved['requested_time_support'].dtype.kind!='b' or saved['protocol_version'].shape!=():raise ValueError('Compact recovery protocol/mask dtype mismatch')
        frozen_times=np.asarray(saved['times_minutes'],float);actual=np.asarray(saved['actual_times_minutes'],float);mask=np.asarray(saved['requested_time_support'],bool);hashes=np.asarray(saved['frame_sha256'])
        prediction=np.asarray(saved['trajectory_predicted'] if 'trajectory_predicted' in saved else saved['predicted'],float)
        if not np.array_equal(frozen_times,times) or actual.shape!=times.shape or mask.shape!=times.shape or hashes.shape!=times.shape or prediction.shape!=(len(times),30):raise ValueError('Compact recovery NPZ shape/times mismatch')
        texts=[value.decode() if isinstance(value,bytes) else str(value) for value in hashes]
        observed=np.array([bool(value) for value in texts]);indices=np.flatnonzero(observed)
        if len(indices) and not np.array_equal(indices,np.arange(indices[-1]+1)):raise ValueError('Compact recovery frame sequence has gaps')
        if np.any(mask&~observed) or any(value and re.fullmatch('[0-9a-f]{64}',value) is None for value in texts):raise ValueError('Compact recovery frame hash/support mismatch')
        if np.any(~np.isfinite(actual[observed])) or np.any(abs(actual[observed]-times[observed])>.500001):raise ValueError('Compact recovery actual frame times mismatch')
        return dict(times_minutes=times,actual_times_minutes=actual,predicted=prediction,requested_time_support=mask,frame_sha256=hashes,stream_identity_sha256=np.array(str(saved['stream_identity_sha256'])),protocol_version=np.array(1),source_npz_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),source_npz_name=path.name)


def recover_mapped_case(directory,expected,times,indices,lookup,outcome):
    """Promote already measured compact rows after a missing wrapper finish.

    Complete/partial outcomes are immutable. Recovered outcomes remain labelled
    partial/interrupted even if all requested observations happen to be present.
    """
    directory=Path(directory);outcome_path=directory/'outcome.json'
    previous=json.loads(outcome_path.read_text()) if outcome_path.exists() else None
    if previous is not None and previous.get('status') in {'complete','partial'}:return previous
    saved=load_compact_evidence(directory,expected,times)
    if saved is None:return None
    indices=np.asarray(indices,int);lookup=np.asarray(lookup,int)
    if indices.shape!=lookup.shape or np.any(lookup<0) or np.any(lookup>=len(times)) or len(np.unique(indices))!=len(indices):raise ValueError('Invalid frozen compact recovery observation map')
    supported=saved['requested_time_support'][lookup];selected=indices[supported];prediction=saved['predicted'][lookup[supported]]
    mapped=directory/'observables.npz'
    if mapped.exists():
        with np.load(mapped,allow_pickle=False) as values:
            if not np.array_equal(values['indices'],selected) or not np.array_equal(values['predicted'],prediction,equal_nan=True):raise ValueError('Existing mapped compact evidence differs from frozen stream')
    else:
        write_npz(mapped,indices=selected,predicted=prediction,trajectory_predicted=saved['predicted'],times_minutes=saved['times_minutes'],actual_times_minutes=saved['actual_times_minutes'],requested_indices=indices,requested_time_support=saved['requested_time_support'],frame_sha256=saved['frame_sha256'],stream_identity_sha256=saved['stream_identity_sha256'],protocol_version=saved['protocol_version'])
    result=dict(outcome,status='partial' if saved['requested_time_support'].any() else 'failed',engine_status='interrupted_recovered',recovered_from_compact_stream=True,recovery_model_calls=0,source_stream_npz_sha256=saved['source_npz_sha256'],source_stream_npz_name=saved['source_npz_name'],stream_identity_sha256=str(saved['stream_identity_sha256']),requested_observations=len(indices),measured_observations=int(supported.sum()),requested_snapshots=len(times),measured_snapshots=int(saved['requested_time_support'].sum()),error='Wrapper completion unavailable; exact saved compact measurements recovered without engine/model calls')
    if previous is not None:result['prior_outcome_sha256']=hashlib.sha256(outcome_path.read_bytes()).hexdigest()
    write_json(outcome_path,result);finalize_compact_case(directory);return result
