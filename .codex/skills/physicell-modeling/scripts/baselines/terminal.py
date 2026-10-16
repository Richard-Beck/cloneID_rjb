"""Portable 190611 selection and manifests; no scientific model is imported here.

Rules come from the executed select_screen.py/native_finalize.py, not the unused
native_pipeline.select_screen variant. Numerical native diagnostics and bounded
refinement remain separately gated scientific worker operations.
"""
from pathlib import Path
import math
import time

import numpy as np
import pandas as pd
from scipy.special import logit, log_expit, xlogy

import workflow as w


def encode(x, bounds):
    bounds=np.asarray(bounds,float);x=np.asarray(x,float)
    width=np.diff(bounds,axis=1).ravel();z=(x-bounds[:,0])/width
    eps=1e-12;length=float(logit(1-eps))
    z[:2]=(logit(np.clip(x[:2],eps,1-eps))+length)/(2*length)
    active=np.array([j for j in range(33) if j!=2])
    return np.clip(z[active],0.,1.)


def quality_diversity(pool, config):
    """Exactly the source top5 then5 maximin rule, with explicit configured counts."""
    settings=config["perspective"]["conditional"]
    quality=settings["screen_quality_per_alpha"];count=settings["screen_candidates_per_alpha"]
    pool=sorted(pool,key=lambda c:(c["final"]["loss"],c["id"]))
    if len(pool)<count:raise w.SetupError(f"Screen selection needs {count} finite final candidates per alpha; got {len(pool)}")
    chosen=pool[:quality]
    near=pool[:max(settings["screen_candidate_pool_floor"],min(settings["screen_candidate_pool_cap"],int(len(pool)*settings["screen_candidate_pool_fraction"])))]
    coordinates={c["id"]:encode(c["final"]["x"],config["perspective"]["bounds"]) for c in near}
    while len(chosen)<count:
        available=[c for c in near if c["id"] not in {q["id"] for q in chosen}]
        if not available:raise w.SetupError("Screen diversity pool exhausted; no silent pool expansion")
        def key(c):
            distance=min(float(np.linalg.norm(coordinates[c["id"]]-encode(q["final"]["x"],config["perspective"]["bounds"]))) for q in chosen)
            return -distance,c["final"]["loss"],c["id"]
        chosen.append(min(available,key=key))
    return chosen


def select_screen(run):
    run,config,identity=w.run_check(run);root=run/"perspective"
    destination=root/"screen_candidates.json"
    if destination.exists():raise w.SetupError("Screen selection is already frozen; no overwrite")
    candidates=w.read(root/"candidates.json");eligible=[];missing=[];invalid=[];details=[];selected=[]
    for c in candidates:
        path=root/"candidates"/c["id"]/"final.json"
        if not path.exists():missing.append(c["id"]);continue
        value=w.read(path)
        if value.get("valid") and math.isfinite(value.get("loss",math.inf)) and value["loss"]<1e24:
            eligible.append(dict(c,final=value))
        else:invalid.append(c["id"])
    settings=config["perspective"]["conditional"]
    for alpha in config["perspective"]["alphas"]:
        pool=[c for c in eligible if c["alpha"]==alpha]
        chosen=quality_diversity(pool,config)
        for rank,c in enumerate(chosen):
            v=c["final"];record={k:value for k,value in c.items() if k!="final"}
            record.update(x=v["x"],screen_selection="objective_top"+str(settings["screen_quality_per_alpha"]) if rank<settings["screen_quality_per_alpha"] else "parameter_diversity",selection_rank=rank,approximation_loss=v["loss"],approximation_data_loss=v["data_loss"],approximation_assay_deviance=v["assay_deviance"],source="candidates/"+c["id"]+"/final.json",source_sha256=w.sha(root/"candidates"/c["id"]/"final.json"))
            selected.append(record)
        details.append({"alpha":alpha,"eligible":len(pool)})
    parents=w.read(root/"parents.json")["shared"]
    if len(parents)<settings["permanent_anchors"]:raise w.SetupError("Insufficient current-run shared parents for permanent screen anchors")
    assays=w.read(run/"inputs/assays.json");episodes=w.read(run/"inputs/episodes.json");byid={e["episode_id"]:e for e in episodes}
    for ai,parent in enumerate(parents[:settings["permanent_anchors"]]):
        alpha=config["perspective"]["alphas"][ai];cid="anchor_"+parent["id"];xx=np.asarray(parent["x"]);assay_values=[]
        founder={g:float(xx[i]) for i,g in enumerate(config["perspective"]["groups"])}
        for q in assays:
            f=founder[byid[q["episode_id"]]["founding_group"]];z=float(logit(f));k=q["k"];n=q["n"]
            dev=float(2*(xlogy(k,k/n)+xlogy(n-k,1-k/n)-k*log_expit(z)-(n-k)*log_expit(-z)))
            assay_values.append(dict(q,predicted_high=f,log_odds=z,deviance=dev))
        reference=parent["reference"];assay=float(np.mean([q["deviance"] for q in assay_values]))
        ac={"id":cid,"family":"no_wgd","alpha":alpha,"seed":config["perspective"]["seed_search"]+9000+ai,"initial":xx.tolist(),"x":xx.tolist(),"parent":parent["id"],"parent_run_id":identity["run_id"],"origin":"Exact unchanged current-run shared physical anchor","source":"candidates/"+cid+"/final.json","screen_selection":"permanent_exact_shared_anchor","approximation_loss":reference["approximation_data_loss"]+assay+reference["assumption_penalty"]}
        nat={"founder_high":founder,"w":0.,"dmax":0.,"q":1.,"rho0":float(np.exp(xx[5])),"m0":float(np.exp(xx[6])),"low":np.exp(xx[7:20]).tolist(),"high":np.exp(xx[20:33]).tolist()}
        final={"candidate":ac,"x":xx.tolist(),"family":"no_wgd","alpha":alpha,"valid":True,"count_offset":config["observation"]["count_offset"],"status":"exact_shared_anchor","data_loss":reference["approximation_data_loss"],"assay_deviance":assay,"assays":assay_values,"assumption_penalty":reference["assumption_penalty"],"ridge_penalty":0.,"parameter_difference":0.,"loss":ac["approximation_loss"],"natural_parameters":nat,"seed_fractions":{q["episode_id"]:founder[q["founding_group"]] for q in episodes}}
        path=root/ac["source"]
        if path.exists():raise w.SetupError("Anchor final already exists; no overwrite")
        w.write(path,final);ac["source_sha256"]=w.sha(path)
        replace=max(j for j,c in enumerate(selected) if c["alpha"]==alpha)
        selected[replace]=ac
    for detail in details:detail["selected"]=[c["id"] for c in selected if c["alpha"]==detail["alpha"]]
    w.write(destination,selected)
    w.write(root/"audit/screen_selection.json",{"eligible_total":len(eligible),"missing_final_count":len(missing),"missing":missing,"invalid":invalid,"selected_count":len(selected),"rule":"Executed select_screen: top5 objective plus5 maximin transformed distance among top100 or60percent (floor30); deterministic loss/ID ties; two anchors replace last diversity slots in first two alpha buckets","buckets":details,"run_id":identity["run_id"]})
    return selected


class Metadata:
    """Episode/support metadata only; no colony trajectory is calculated."""
    def __init__(self,run,config):
        self.rows=pd.read_csv(run/"inputs/observations.csv")
        self.episodes=w.read(run/"inputs/episodes.json");self.assays=w.read(run/"inputs/assays.json")
        self.dt={o:float(self.rows.loc[self.rows.oxygen.eq(o),"time_days"].max())/config["perspective"]["steps"] for o in {p["oxygen"] for p in self.episodes}}
        self.plans={p["episode_id"]:np.unique(np.round(p["needed_times_days"]+[q["time_days"] for q in self.assays if q["episode_id"]==p["episode_id"]],10)) for p in self.episodes}


def subset(data,count):
    """Executed native_pipeline.subset selection, with count explicit in config."""
    chosen=[]
    def add(p):
        if p["episode_id"] not in {r["episode_id"] for r in chosen}:chosen.append(p)
    for oxygen in sorted(data.dt):
        for group in ["2N","4N"]:
            ps=[p for p in data.episodes if p["oxygen"]==oxygen and p["founding_group"]==group]
            if not ps:raise w.SetupError("Missing founder/oxygen screen support")
            add(max(ps,key=lambda p:(p["duration_days"],p["episode_id"])))
    for p in data.episodes:
        if p["parent_episode_id"] is None:add(p)
    for group in ["2N","4N"]:
        for arm in ["C","O1","O2"]:
            ps=[p for p in data.episodes if p["founding_group"]==group and p["arm"]==arm]
            if not ps:raise w.SetupError("Missing founder/arm screen support")
            add(ps[-1])
    for group in ["2N","4N"]:
        ps=[p for p in data.episodes if p["founding_group"]==group and p["arm"] in ["O1","O2"] and p not in chosen]
        if len(chosen)<count:
            if not ps:raise w.SetupError("Insufficient short hypoxic passage support")
            add(min(ps,key=lambda p:(p["duration_days"],p["episode_id"])))
    while len(chosen)<count:
        ps=[p for p in data.episodes if p not in chosen]
        if not ps:raise w.SetupError("Screen passage count exceeds available episodes")
        add(max(ps,key=lambda p:min(abs(p["duration_days"]-q["duration_days"])+float(p["oxygen"]!=q["oxygen"]) for q in chosen)))
    return chosen[:count]


def prepare_native(run,stage,candidates=None):
    run,config,identity=w.run_check(run);root=run/"perspective";settings=config["perspective"]["conditional"]
    if stage not in {"screen","final_validation"}:raise w.SetupError("Unknown native stage")
    out=root/stage
    if (out/"stage_identity.json").exists():raise w.SetupError("Native stage already frozen; no overwrite")
    data=Metadata(run,config)
    if candidates is None:candidates=w.read(root/("screen_candidates.json" if stage=="screen" else "finalists.json"))
    passages=subset(data,settings["screen_passages"]) if stage=="screen" else data.episodes
    reps=settings["screen_replicates"] if stage=="screen" else settings["final_replicates"]
    slots=[]
    for c in candidates:
        cid=c["id"];source=(root/c["source"]).resolve()
        if not w.inside(source,root):raise w.SetupError("Native source outside this new run")
        if c.get("source_sha256") and w.sha(source)!=c["source_sha256"]:raise w.SetupError("Selected native source changed")
        final=w.read(source)
        if not final.get("valid"):raise w.SetupError("Invalid selected native candidate: "+cid)
        value=dict(final,x=c["x"],alpha=c["alpha"],candidate_id=cid,source_sha256=w.sha(source),source=str(source.relative_to(root)))
        if c.get("correction") is not None:value["native_correction"]=c["correction"]
        w.write(out/"frozen"/cid/"final.json",value)
        for p in passages:
            ei=data.episodes.index(p);horizon=max([p["duration_days"]]+p["needed_times_days"]+[q["time_days"] for q in p["children"]])
            times=sorted(set(np.round([0.,horizon]+p["needed_times_days"]+data.plans[p["episode_id"]].tolist(),10)))
            for rep in range(reps):slots.append({"kind":"main","candidate_id":cid,"alpha":c["alpha"],"episode_index":ei,"episode_id":p["episode_id"],"founding_group":p["founding_group"],"arm":p["arm"],"oxygen":p["oxygen"],"replicate":rep,"seed":config["perspective"]["seed_native"]+(100000 if stage!="screen" else 0)+10000*rep+ei,"initial_high_fraction":value["seed_fractions"][p["episode_id"]],"harvest_time_days":horizon,"times_days":times,"observation_rows":p["observation_rows"]})
        for oi,oxygen in enumerate(sorted(data.dt)):
            ps=[p for p in data.episodes if p["oxygen"]==oxygen];anchor=max(ps,key=lambda p:p["duration_days"]);hs=sorted(set(p["duration_days"] for p in ps))
            for fi,fraction in enumerate(settings["minority_probe_fractions"]):
                for rep in range(reps):slots.append({"kind":"minority_probe","candidate_id":cid,"alpha":c["alpha"],"episode_index":data.episodes.index(anchor),"episode_id":anchor["episode_id"],"founding_group":"probe","arm":"probe","oxygen":oxygen,"replicate":rep,"seed":config["perspective"]["seed_native"]+1000000+(100000 if stage!="screen" else 0)+10000*rep+100*oi+fi,"initial_high_fraction":fraction,"harvest_time_days":max(hs),"times_days":sorted(set([0.]+hs)),"observation_rows":[]})
    slots.sort(key=lambda s:(-s["harvest_time_days"],s["kind"]!="minority_probe",s["candidate_id"],s["replicate"]))
    for i,slot in enumerate(slots):slot["case_index"]=i
    w.write(out/"slots.json",slots);w.write(out/"candidates.json",candidates)
    w.write(out/"contract.json",{"stage":stage,"run_id":identity["run_id"],"candidates":len(candidates),"passages":len(passages),"replicates":reps,"total_cases":len(slots),"minority_probe_fractions":settings["minority_probe_fractions"],"oxygen_values":sorted(data.dt),"timeout_seconds":config["perspective"]["native_timeout_seconds"],"randomized_state_initialization":True,"native_integer_inheritance":False,"coefficients":config["observation"]["coefficients"],"case_order":"longest duration first; probes first at equal duration"})
    w.write(out/"parameter_manifest.json",{c["id"]:w.sha(out/"frozen"/c["id"]/"final.json") for c in candidates})
    duration=settings["native_stage_deadline_seconds"][stage];now=time.time()
    w.write(out/"stage_identity.json",{"stage":stage,"run_id":identity["run_id"],"prepared_unix":now,"relative_deadline_seconds":duration,"deadline_unix":now+duration if duration is not None else None,"deadline_origin":settings["deadline_origin"],"accept_after_planned_validation":True,"additional_adaptive_batches":False})
    files=[out/name for name in ["slots.json","candidates.json","contract.json","parameter_manifest.json","stage_identity.json"]]
    files += [run/"inputs"/name for name in ["observations.npz","episodes.json","assays.json"]]
    files += [w.resolve(config,"perspective_engine"),w.PACKAGE/"vendor/wgd_transfer.py",w.PACKAGE/"vendor/core/transfer.py"]
    w.write(out/"support_manifest.json",{"run_id":identity["run_id"],"files":[{"path":str(path.resolve()),"sha256":w.sha(path)} for path in files]})
    return slots


def verify_native_stage(run,stage):
    run,config,identity=w.run_check(run)
    manifest=w.read(run/"perspective"/stage/"support_manifest.json")
    if manifest["run_id"]!=identity["run_id"]:raise w.SetupError("Foreign native support manifest")
    for item in manifest["files"]:
        if w.sha(item["path"])!=item["sha256"]:raise w.SetupError("Frozen native support changed: "+item["path"])


def refinement_eligibility(root,candidate):
    """Executed refinement's availability rules, without evaluating its objective."""
    root=Path(root);cid=candidate["id"];source=root/"candidates"/cid/"final.json"
    if not source.exists():return {"eligible":False,"status":"failed","reason":"missing_source_final"}
    if cid.startswith("anchor_"):return {"eligible":False,"status":"retained_immutable_anchor"}
    directory=root/"screen/analysis"/cid
    if not (directory/"summary.json").exists():return {"eligible":False,"status":"failed","reason":"missing_screen_summary"}
    summary=w.read(directory/"summary.json")
    if summary.get("failures"):return {"eligible":False,"status":"skipped_incomplete_native_parent","failures":summary["failures"]}
    if not (directory/"microscopy_scores.json").exists() or not (directory/"correction.json").exists():return {"eligible":False,"status":"failed","reason":"missing_screen_analysis"}
    microscopy=w.read(directory/"microscopy_scores.json");bias=microscopy.get("native_minus_approximation_bias")
    if bias is None or not math.isfinite(float(bias)):return {"eligible":False,"status":"skipped_invalid_native_microscopy"}
    source_value=w.read(source);correction=w.read(directory/"correction.json")
    if not np.allclose(source_value["x"],correction["source_x"],rtol=0.,atol=1e-12):return {"eligible":False,"status":"failed","reason":"correction_source_vector_mismatch"}
    return {"eligible":True,"status":"eligible_bounded_refinement"}


def finalist_choice(records,config):
    records=sorted(records,key=lambda v:(v["selection_score"],v["id"]))
    unique=[];sources=set()
    for record in records:
        if record["source_id"] not in sources:unique.append(record);sources.add(record["source_id"])
    if len(unique)<3:raise w.SetupError("Need three supported distinct-source finalists; got "+str(len(unique)))
    finalists=unique[:2];settings=config["perspective"]["conditional"]
    limit=unique[0]["selection_score"]+max(settings["finalist_competitive_absolute"],settings["finalist_competitive_fraction"]*abs(unique[0]["selection_score"]))
    pool=[c for c in unique[2:settings["finalist_diversity_pool_stop"]] if c["selection_score"]<=limit]
    fallback=not bool(pool)
    if not pool:pool=unique[2:3]
    coordinates=np.array([encode(c["x"],config["perspective"]["bounds"]) for c in finalists])
    third=max(pool,key=lambda c:(float(np.min(np.mean((coordinates-encode(c["x"],config["perspective"]["bounds"]))**2,axis=1))),-c["selection_score"],c["id"]))
    finalists.append(third)
    return finalists,{"distinct_supported_sources":len(unique),"competitive_limit":limit,"third_fallback_to_next_supported":fallback,"third_pool":[c["id"] for c in pool]}


def select_finalists(run):
    run,config,identity=w.run_check(run);root=run/"perspective"
    if (root/"finalists.json").exists():raise w.SetupError("Finalist selection already frozen; no overwrite")
    candidates=w.read(root/"screen/candidates.json");records=[];excluded=[]
    for c in candidates:
        cid=c["id"];directory=root/"screen/analysis"/cid
        required=[directory/name for name in ["summary.json","microscopy_scores.json","correction.json"]]
        if not all(path.exists() for path in required):excluded.append({"id":cid,"reason":"missing_screen_analysis"});continue
        summary,micro,correction=map(w.read,required)
        if micro["total"] is None or summary["failures"]:excluded.append({"id":cid,"reason":"unsupported_screen","failures":summary["failures"]});continue
        options=[(cid,directory/"corrected_final.json",True)]
        for path in [root/"refinement"/cid/"final.json",root/"candidates"/("refined_"+cid)/"final.json"]:
            if path.exists():options.append(("refined_"+cid,path,False));break
        for label,path,original in options:
            if not path.exists():excluded.append({"id":label,"reason":"missing_corrected_source"});continue
            value=w.read(path)
            if not value.get("valid"):excluded.append({"id":label,"reason":"invalid_corrected_source"});continue
            terms=[value.get("data_loss"),micro.get("native_minus_approximation_bias",0.),value.get("assay_deviance"),value.get("ridge_penalty")]
            if any(v is None or not math.isfinite(v) for v in terms):excluded.append({"id":label,"reason":"nonfinite_selection_terms"});continue
            records.append({"id":label,"source_id":cid,"alpha":c["alpha"],"x":value["x"],"source":str(path.relative_to(root)),"correction":correction,"selection_score":sum(terms),"corrected_cohort_microscopy":value["data_loss"],"native_screen_microscopy":micro["total"],"native_image_bias":micro.get("native_minus_approximation_bias"),"corrected_assay_deviance":value["assay_deviance"],"ridge_penalty":value["ridge_penalty"],"physical_refined":not original,"source_sha256":w.sha(path)})
    records.sort(key=lambda v:(v["selection_score"],v["id"]))
    try:finalists,selection=finalist_choice(records,config)
    except w.SetupError as error:
        w.write(root/"audit/finalist_selection.json",{"status":"blocked","error":str(error),"excluded":excluded,"supported_options":len(records),"run_id":identity["run_id"]})
        raise
    for i,c in enumerate(finalists):c["finalist_reason"]="Two best native-informed supported distinct sources" if i<2 else "Parameter-diverse competitive third; source-defined next-supported fallback if none competitive"
    w.write(root/"finalists.json",finalists);w.write(root/"native_informed_ranking.json",records)
    w.write(root/"audit/finalist_selection.json",{"status":"selected","selected":[c["id"] for c in finalists],"excluded":excluded,"selection":selection,"run_id":identity["run_id"]})
    prepare_native(run,"final_validation",finalists)
    return finalists
