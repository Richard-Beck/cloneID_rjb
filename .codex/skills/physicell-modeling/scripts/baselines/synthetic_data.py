"""Generate invented fixtures for orchestration tests; never reads laboratory data."""
from pathlib import Path
import csv
import json
import numpy as np


def write_json(path,value):
    Path(path).write_text(json.dumps(value,indent=2)+"\n")


def write_csv(path,rows):
    with Path(path).open("w",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def build(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    rows=[];episodes=[];fields=[];assays=[]
    oxygen_values=[20.5,5.,2.,1.,.5,.2,.1,.05]
    for group_index,group in enumerate(["2N","4N"]):
        root_id="synthetic_"+group+"_root"
        local=[("common",0)] + [(arm,i) for arm,count in [("C",20),("O1",19),("O2",19)] for i in range(count)]
        last={}
        for local_index,(arm,passage) in enumerate(local):
            eid=root_id if arm=="common" else f"synthetic_{group}_{arm}_{passage:02}"
            parent=None if arm=="common" else last.get(arm,root_id)
            last[arm]=eid
            duration=2.+.125*(local_index%9)
            oxygen=20.5 if arm in ["common","C"] else oxygen_values[passage%len(oxygen_values)]
            nrows=3 if len(episodes)<107 else 2
            times=[0.,.5,1.] if nrows==3 else [0.,1.]
            indices=[]
            for time in times:
                index=len(rows);indices.append(index)
                rows.append({"episode_id":eid,"passage_id":eid,"group":group,"arm":arm,"time_days":time,"oxygen":oxygen,"count":100,"total_count":100,"live_count":90,"dead_count":10,"synthetic":True})
                for field in range(4 if index<336 else 3):fields.append({"row":index,"n_cells":100,"live_count":90,"dead_count":10,"synthetic":True})
            episodes.append({"episode_id":eid,"parent_episode_id":parent,"parent_transfer_time_days":None if parent is None else 1.,"founding_group":group,"arm":arm,"oxygen":oxygen,"observation_rows":indices,"observation_times_days":times,"duration_days":duration,"needed_times_days":sorted(set(times+[duration])),"children":[],"synthetic":True})
        for i in range(5):assays.append({"id":f"synthetic_assay_{group}_{i}","episode_id":root_id,"group":group,"founding_group":group,"k":2 if group_index==0 else 20,"n":22,"time_days":0.,"synthetic":True})
    byid={p["episode_id"]:p for p in episodes}
    for episode in episodes:
        if episode["parent_episode_id"] is not None:byid[episode["parent_episode_id"]]["children"].append({"child_episode_id":episode["episode_id"],"time_days":episode["parent_transfer_time_days"]})
    assert (len(rows),len(episodes),len(fields),len(assays))==(343,118,1365,10)
    observed=np.zeros((len(rows),30));observed[:,0]=np.log1p(100);observed[:,1]=np.log1p(10);observed[:,2]=.2;observed[:,4]=1.
    weights=np.zeros((len(rows),6))
    for episode in episodes:weights[episode["observation_rows"]]=.5/59/len(episode["observation_rows"])
    np.savez_compressed(root/"observations.npz",observed=observed,scales=np.ones_like(observed),weights=weights)
    write_csv(root/"observations.csv",rows);write_csv(root/"field_measurements.csv",fields)
    write_json(root/"episodes.json",episodes);write_json(root/"assays.json",assays)
    write_json(root/"metadata.json",{"synthetic":True,"source":"invented fixture; not a scientific observation"})
    for name in ["lineage_edges.csv","schedule_all.csv","excluded_schedule.csv"]:write_csv(root/name,[{"synthetic":True}])
    return root


def configure(config,scratch,prepared,python):
    """All generated prerequisites/output remain under this test's scratch root."""
    import hashlib
    scratch=Path(scratch).resolve();prepared=Path(prepared).resolve()
    engines=scratch/"mock_engines";engines.mkdir(parents=True,exist_ok=True)
    for name in ["lineage","perspective"]:
        path=engines/name;path.write_text("SYNTHETIC PLACEHOLDER. MUST NEVER BE EXECUTED.\n");path.chmod(0o700)
    config["paths"].update(prepared_data=str(prepared),scratch_root=str(scratch),output_root=str(scratch/"runs"),python=str(Path(python).resolve()),lineage_engine=str(engines/"lineage"),perspective_engine=str(engines/"perspective"))
    config["inputs"]["required"]=[path.name for path in sorted(prepared.iterdir())]
    config["inputs"]["prepared_hashes"]={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(prepared.iterdir())}
    return config
