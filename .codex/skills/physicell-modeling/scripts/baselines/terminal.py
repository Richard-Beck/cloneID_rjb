"""Portable 190611 selection and manifests; no scientific model is imported here.

Rules come from the executed select_screen.py/native_finalize.py, not the unused
native_pipeline.select_screen variant. Numerical native diagnostics and bounded
refinement remain separately gated scientific worker operations.
"""
from pathlib import Path
import hashlib
import json
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


def finite(value):
    """Missing/non-numeric scores are unavailable, never zero-valued evidence."""
    try:return value is not None and math.isfinite(float(value))
    except (TypeError,ValueError,OverflowError):return False


def valid_vector(value,config):
    try:x=np.asarray(value,float);bounds=np.asarray(config["perspective"]["bounds"],float)
    except (TypeError,ValueError):return False
    return x.shape==(33,) and np.isfinite(x).all() and bool(((x>=bounds[:,0]-1e-12)&(x<=bounds[:,1]+1e-12)).all())


def selected_source(root,candidate):
    """Selection scarcity may degrade; a changed or foreign source cannot."""
    root=Path(root);source=(root/candidate.get("source","candidates/"+candidate["id"]+"/final.json")).resolve()
    if not w.inside(source,root):raise w.SetupError("Selected source outside this new run")
    if candidate.get("source_sha256"):
        if not source.exists() or w.sha(source)!=candidate["source_sha256"]:raise w.SetupError("Selected native source changed")
    return source


def check_correction_source(root,candidate,source_value,correction):
    try:original=np.asarray(source_value["x"],float);actual=np.asarray(correction["source_x"],float)
    except (KeyError,TypeError,ValueError):raise w.SetupError("Invalid native correction source vector")
    if original.shape!=actual.shape or not np.allclose(original,actual,rtol=0.,atol=1e-12):raise w.SetupError("Correction source vector mismatch")
    if correction.get("source_sha256"):
        frozen=Path(root)/"screen/frozen"/candidate["id"]/"final.json"
        if not frozen.exists() or w.sha(frozen)!=correction["source_sha256"]:raise w.SetupError("Native correction source changed")


def quality_diversity(pool, config):
    """Source top5 then5 maximin rule, retaining fewer when evidence is scarce."""
    settings=config["perspective"]["conditional"]
    quality=settings["screen_quality_per_alpha"];count=settings["screen_candidates_per_alpha"]
    pool=sorted([c for c in pool if c["final"].get("valid") and finite(c["final"].get("loss")) and valid_vector(c["final"].get("x"),config)],key=lambda c:(c["final"]["loss"],c["id"]))
    count=min(count,len(pool));chosen=pool[:min(quality,count)]
    near=pool[:max(count,settings["screen_candidate_pool_floor"],min(settings["screen_candidate_pool_cap"],int(len(pool)*settings["screen_candidate_pool_fraction"])))]
    coordinates={c["id"]:encode(c["final"]["x"],config["perspective"]["bounds"]) for c in near}
    while len(chosen)<count:
        available=[c for c in near if c["id"] not in {q["id"] for q in chosen}]
        if not available:break
        def key(c):
            distance=min((float(np.linalg.norm(coordinates[c["id"]]-encode(q["final"]["x"],config["perspective"]["bounds"]))) for q in chosen),default=0.)
            return -distance,c["final"]["loss"],c["id"]
        chosen.append(min(available,key=key))
    return chosen


def select_screen(run):
    run,config,identity=w.run_check(run);root=run/"perspective"
    destination=root/"screen_candidates.json"
    if destination.exists():raise w.SetupError("Screen selection is already frozen; no overwrite")
    if (root/"embedding_check.json").exists():
        embedding=w.read(root/"embedding_check.json")
        for name,key in [("parents.json","parents_sha256"),("candidates.json","candidates_sha256")]:
            if embedding.get(key) is not None and w.sha(root/name)!=embedding[key]:raise w.SetupError("Finalized embedding manifest changed: "+name)
    candidates=w.read(root/"candidates.json") if (root/"candidates.json").exists() else [];eligible=[];missing=[];invalid=[];details=[];selected=[]
    for c in candidates:
        if c.get("parent_run_id",identity["run_id"])!=identity["run_id"]:raise w.SetupError("Foreign screen candidate parent")
        path=(root/"candidates"/c["id"]/"final.json").resolve()
        if not w.inside(path,root/"candidates"):raise w.SetupError("Screen candidate source outside this new run")
        if not path.exists():missing.append(c["id"]);continue
        value=w.read(path)
        if value.get("valid") and finite(value.get("loss")) and valid_vector(value.get("x"),config):
            eligible.append(dict(c,final=value))
        else:invalid.append(c["id"])
    settings=config["perspective"]["conditional"]
    for alpha in config["perspective"]["alphas"]:
        pool=[c for c in eligible if c["alpha"]==alpha]
        chosen=quality_diversity(pool,config)
        for rank,c in enumerate(chosen):
            v=c["final"];record={k:value for k,value in c.items() if k!="final"}
            record.update(x=v["x"],screen_selection="objective_top"+str(settings["screen_quality_per_alpha"]) if rank<settings["screen_quality_per_alpha"] else "parameter_diversity",selection_rank=rank,approximation_loss=v["loss"],approximation_data_loss=v.get("data_loss"),approximation_assay_deviance=v.get("assay_deviance"),ranking_basis="approximation_source_loss",native_support="not_yet_evaluated",source="candidates/"+c["id"]+"/final.json",source_sha256=w.sha(root/"candidates"/c["id"]/"final.json"))
            selected.append(record)
        details.append({"alpha":alpha,"eligible":len(pool)})
    parent_manifest=w.read(root/"parents.json") if (root/"parents.json").exists() else {}
    if parent_manifest.get("parent_run_id",identity["run_id"])!=identity["run_id"]:raise w.SetupError("Foreign shared anchor parents")
    parents=parent_manifest.get("shared",[]);invalid_anchors=[];anchors_added=0
    assays=w.read(run/"inputs/assays.json");episodes=w.read(run/"inputs/episodes.json");byid={e["episode_id"]:e for e in episodes}
    for parent in parents:
        if anchors_added>=settings["permanent_anchors"]:break
        ai=anchors_added
        if parent.get("run_id",identity["run_id"])!=identity["run_id"]:raise w.SetupError("Foreign shared anchor parent")
        if not valid_vector(parent.get("x"),config) or any(not finite(parent.get("reference",{}).get(k)) for k in ["approximation_data_loss","assumption_penalty"]):
            invalid_anchors.append(parent.get("id"));continue
        alpha=config["perspective"]["alphas"][ai];cid="anchor_"+parent["id"];xx=np.asarray(parent["x"]);assay_values=[]
        founder={g:float(xx[i]) for i,g in enumerate(config["perspective"]["groups"])}
        for q in assays:
            f=founder[byid[q["episode_id"]]["founding_group"]];z=float(logit(f));k=q["k"];n=q["n"]
            dev=float(2*(xlogy(k,k/n)+xlogy(n-k,1-k/n)-k*log_expit(z)-(n-k)*log_expit(-z)))
            assay_values.append(dict(q,predicted_high=f,log_odds=z,deviance=dev))
        reference=parent["reference"];assay=float(np.mean([q["deviance"] for q in assay_values])) if assay_values else None
        if not finite(assay):invalid_anchors.append(parent["id"]);continue
        ac={"id":cid,"family":"no_wgd","alpha":alpha,"seed":config["perspective"]["seed_search"]+9000+ai,"initial":xx.tolist(),"x":xx.tolist(),"parent":parent["id"],"parent_run_id":identity["run_id"],"origin":"Exact unchanged current-run shared physical anchor","source":"candidates/"+cid+"/final.json","screen_selection":"permanent_exact_shared_anchor","approximation_loss":reference["approximation_data_loss"]+assay+reference["assumption_penalty"]}
        nat={"founder_high":founder,"w":0.,"dmax":0.,"q":1.,"rho0":float(np.exp(xx[5])),"m0":float(np.exp(xx[6])),"low":np.exp(xx[7:20]).tolist(),"high":np.exp(xx[20:33]).tolist()}
        final={"candidate":ac,"x":xx.tolist(),"family":"no_wgd","alpha":alpha,"valid":True,"count_offset":config["observation"]["count_offset"],"status":"exact_shared_anchor","data_loss":reference["approximation_data_loss"],"assay_deviance":assay,"assays":assay_values,"assumption_penalty":reference["assumption_penalty"],"ridge_penalty":0.,"parameter_difference":0.,"loss":ac["approximation_loss"],"natural_parameters":nat,"seed_fractions":{q["episode_id"]:founder[q["founding_group"]] for q in episodes}}
        path=root/ac["source"]
        if path.exists():raise w.SetupError("Anchor final already exists; no overwrite")
        w.write(path,final);ac["source_sha256"]=w.sha(path)
        ac.update(ranking_basis="approximation_source_loss",native_support="not_yet_evaluated")
        bucket=[j for j,c in enumerate(selected) if c["alpha"]==alpha]
        if len(bucket)>=settings["screen_candidates_per_alpha"]:selected[max(bucket)]=ac
        elif bucket:selected.insert(max(bucket)+1,ac)
        else:selected.append(ac)
        anchors_added+=1
    for detail in details:detail["selected"]=[c["id"] for c in selected if c["alpha"]==detail["alpha"]]
    w.write(destination,selected)
    expected=settings["screen_candidates_per_alpha"]*len(config["perspective"]["alphas"])
    degraded=len(selected)<expected or anchors_added<settings["permanent_anchors"] or parent_manifest.get("degraded",False)
    w.write(root/"audit/screen_selection.json",{"status":"unavailable" if not selected else "degraded" if degraded else "selected","degraded":degraded,"eligible_total":len(eligible),"missing_final_count":len(missing),"missing":missing,"invalid":invalid,"invalid_anchors":invalid_anchors,"anchors_available":anchors_added,"anchors_requested":settings["permanent_anchors"],"selected_count":len(selected),"requested_count":expected,"scores_fabricated":False,"rule":"Executed top5 plus5 maximin with deterministic loss/ID ties; available anchors replace final diversity slots in full buckets or fill unused slots. Scarce buckets retain available finite model-valid sources.","buckets":details,"run_id":identity["run_id"]})
    return selected


class Metadata:
    """Episode/support metadata only; no colony trajectory is calculated."""
    def __init__(self,run,config):
        self.rows=pd.read_csv(run/"inputs/observations.csv")
        self.episodes=w.read(run/"inputs/episodes.json");self.assays=w.read(run/"inputs/assays.json")
        self.dt={o:float(self.rows.loc[self.rows.oxygen.eq(o),"time_days"].max())/config["perspective"]["steps"] for o in {p["oxygen"] for p in self.episodes}}
        self.plans={p["episode_id"]:np.unique(np.round(p["needed_times_days"]+[q["time_days"] for q in self.assays if q["episode_id"]==p["episode_id"]],10)) for p in self.episodes}


def subset(data,count):
    """Source support order, using available episodes when coverage is incomplete."""
    chosen=[]
    def add(p):
        if p["episode_id"] not in {r["episode_id"] for r in chosen}:chosen.append(p)
    for oxygen in sorted(data.dt):
        for group in ["2N","4N"]:
            ps=[p for p in data.episodes if p["oxygen"]==oxygen and p["founding_group"]==group]
            if not ps:continue
            add(max(ps,key=lambda p:(p["duration_days"],p["episode_id"])))
    for p in data.episodes:
        if p["parent_episode_id"] is None:add(p)
    for group in ["2N","4N"]:
        for arm in ["C","O1","O2"]:
            ps=[p for p in data.episodes if p["founding_group"]==group and p["arm"]==arm]
            if not ps:continue
            add(ps[-1])
    for group in ["2N","4N"]:
        ps=[p for p in data.episodes if p["founding_group"]==group and p["arm"] in ["O1","O2"] and p not in chosen]
        if len(chosen)<count:
            if not ps:continue
            add(min(ps,key=lambda p:(p["duration_days"],p["episode_id"])))
    while len(chosen)<count:
        ps=[p for p in data.episodes if p not in chosen]
        if not ps:break
        if not chosen:add(max(ps,key=lambda p:(p["duration_days"],p["episode_id"])));continue
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
        cid=c["id"];source=selected_source(root,c)
        final=w.read(source)
        if not final.get("valid") or not valid_vector(c.get("x"),config):raise w.SetupError("Invalid selected native candidate: "+cid)
        if not np.allclose(final["x"],c["x"],rtol=0.,atol=1e-12):raise w.SetupError("Selected source vector changed: "+cid)
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
    requested_candidates=settings["screen_candidates_per_alpha"]*len(config["perspective"]["alphas"]) if stage=="screen" else settings["finalists"]
    requested_passages=settings["screen_passages"] if stage=="screen" else len(data.episodes)
    missing_coverage=[{"oxygen":o,"founding_group":g} for o in sorted(data.dt) for g in ["2N","4N"] if not any(p["oxygen"]==o and p["founding_group"]==g for p in passages)]
    degraded=len(candidates)<requested_candidates or len(passages)<requested_passages or bool(missing_coverage) or any(c.get("native_support") not in {None,"complete","not_yet_evaluated"} for c in candidates) or stage=="final_validation" and any(c.get("ranking_basis")=="approximation_source_loss" for c in candidates)
    w.write(out/"contract.json",{"stage":stage,"run_id":identity["run_id"],"status":"unavailable" if not candidates else "degraded" if degraded else "prepared","degraded":degraded,"candidates":len(candidates),"requested_candidates":requested_candidates,"passages":len(passages),"requested_passages":requested_passages,"missing_founder_oxygen_support":missing_coverage,"replicates":reps,"total_cases":len(slots),"unused_planned_indices":"workers skip indices beyond these frozen dynamic manifests","scores_fabricated":False,"minority_probe_fractions":settings["minority_probe_fractions"],"oxygen_values":sorted(data.dt),"timeout_seconds":config["perspective"]["native_timeout_seconds"],"randomized_state_initialization":True,"native_integer_inheritance":False,"coefficients":config["observation"]["coefficients"],"case_order":"longest duration first; probes first at equal duration"})
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
    root=Path(root);cid=candidate["id"];source=selected_source(root,candidate)
    if not source.exists():return {"eligible":False,"status":"skipped_unavailable_source","reason":"missing_source_final"}
    if cid.startswith("anchor_"):return {"eligible":False,"status":"retained_immutable_anchor"}
    directory=root/"screen/analysis"/cid
    if not (directory/"summary.json").exists():return {"eligible":False,"status":"skipped_unavailable_native_parent","reason":"missing_screen_summary"}
    summary=w.read(directory/"summary.json")
    if not (directory/"microscopy_scores.json").exists() or not (directory/"correction.json").exists():return {"eligible":False,"status":"skipped_incomplete_native_parent" if summary.get("failures") else "skipped_unavailable_native_parent","reason":"missing_screen_analysis","failures":summary.get("failures",[])}
    microscopy=w.read(directory/"microscopy_scores.json");bias=microscopy.get("ranking_native_minus_approximation_bias",microscopy.get("native_minus_approximation_bias"))
    if not finite(bias):return {"eligible":False,"status":"skipped_invalid_native_microscopy"}
    source_value=w.read(source);correction=w.read(directory/"correction.json")
    check_correction_source(root,candidate,source_value,correction)
    if summary.get("correction_status") in {"unavailable","invalid","failed"}:return {"eligible":False,"status":"skipped_unavailable_native_correction"}
    return {"eligible":True,"status":"eligible_bounded_refinement","native_support":"partial" if summary.get("failures") or microscopy.get("total") is None else "complete","ranking_bias":float(bias)}


def ranking_evidence(record,config):
    """Evidence precedes loss; partial losses with different masks never compete."""
    basis=record.get("ranking_basis","")
    if basis=="approximation_source_loss":tier=2;mass=coverage=None;pattern="approximation_source_loss"
    elif record.get("native_support")=="complete":tier=0;mass=coverage=1.;pattern="complete_native_support"
    elif record.get("native_support")=="partial":
        tier=1;detail=record.get("native_support_detail");rows=detail if isinstance(detail,list) else []
        coefficients=np.asarray(config["observation"]["coefficients"],float);masses=[];fractions=[];patterns=[]
        for row in rows:
            requested=np.asarray(row.get("requested_component_weight",[]),float);available=np.asarray(row.get("supported_component_weight",[]),float)
            if requested.shape==(6,) and available.shape==(6,):
                active=(requested>0)&(coefficients>0);denominator=float(coefficients[active].sum())
                masses.append(float(coefficients[active&(available>0)].sum())/denominator if denominator else 0.)
            else:masses.append(0.)
            fractions.append(float(row["weight_fraction"]) if finite(row.get("weight_fraction")) else 0.)
            patterns.append({k:row.get(k) for k in ["mask","requested_component_weight","component_weight_fraction","missing_components"]})
        requested=max(len(rows),int(record.get("native_requested_replicates") or len(rows) or 1))
        mass=float(sum(masses)/requested) if rows else None
        coverage=float(sum(fractions)/requested) if rows else None
        if not rows and isinstance(detail,dict) and finite(detail.get("completed_rows")) and finite(detail.get("requested_rows")) and detail["requested_rows"]>0:coverage=float(detail["completed_rows"]/detail["requested_rows"])
        payload={"indices":record.get("native_screen_indices"),"replicates":requested,"patterns":patterns,"legacy_support":{k:detail.get(k) for k in ["completed_rows","requested_rows"]} if isinstance(detail,dict) else None}
        pattern=hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()
    else:tier=2;mass=coverage=None;pattern="unlabelled_finite_source"
    record.update(ranking_evidence_tier=tier,ranking_component_mass=mass,ranking_weight_fraction=coverage,ranking_support_pattern=pattern)
    return tier,-(mass if mass is not None else 0.),-(coverage if coverage is not None else 0.),pattern


def comparable_finalists(unique,config):
    """Unchanged executed selection within one comparable evidence group."""
    settings=config["perspective"]["conditional"];target=settings["finalists"];best=min(settings["finalist_best_count"],target)
    empty={"competitive_limit":None,"third_fallback_to_next_supported":False,"third_pool":[]}
    if len(unique)<target or target<=best:return unique[:target],empty
    finalists=unique[:best]
    limit=unique[0]["selection_score"]+max(settings["finalist_competitive_absolute"],settings["finalist_competitive_fraction"]*abs(unique[0]["selection_score"]))
    pool=[c for c in unique[best:settings["finalist_diversity_pool_stop"]] if c["selection_score"]<=limit]
    fallback=not bool(pool)
    if not pool:pool=unique[best:best+1]
    first_pool=[c["id"] for c in pool]
    while len(finalists)<target:
        remaining=[c for c in pool if c["source_id"] not in {q["source_id"] for q in finalists}]
        if not remaining:remaining=[c for c in unique if c["source_id"] not in {q["source_id"] for q in finalists}][:1]
        if not remaining:break
        coordinates=np.array([encode(c["x"],config["perspective"]["bounds"]) for c in finalists])
        chosen=max(remaining,key=lambda c:(float(np.min(np.mean((coordinates-encode(c["x"],config["perspective"]["bounds"]))**2,axis=1))) if len(coordinates) else 0.,-c["selection_score"],c["id"]))
        finalists.append(chosen)
    return finalists,{"competitive_limit":limit,"third_fallback_to_next_supported":fallback,"third_pool":first_pool}


def finalist_choice(records,config):
    target=config["perspective"]["conditional"]["finalists"]
    eligible=[v for v in records if finite(v.get("selection_score")) and valid_vector(v.get("x"),config)]
    groups={}
    for record in eligible:groups.setdefault(ranking_evidence(record,config),[]).append(record)
    # Different partial masks are ordered by evidence mass/coverage, then a
    # deterministic source-ID tie; their numerical losses are never compared.
    ordered=sorted(groups,key=lambda key:(key[:3],min(v["source_id"] for v in groups[key]),key[3]))
    used=set();unique_groups=[];all_records=[];group_audit=[]
    for key in ordered:
        values=sorted(groups[key],key=lambda v:(v["selection_score"],v["id"]));all_records.extend(values);unique=[]
        for record in values:
            if record["source_id"] not in used:unique.append(record);used.add(record["source_id"])
        if unique:unique_groups.append(unique)
        group_audit.append({"tier":key[0],"component_mass":values[0]["ranking_component_mass"],"weight_fraction":values[0]["ranking_weight_fraction"],"support_pattern":key[3],"distinct_sources":[v["source_id"] for v in unique],"record_ids":[v["id"] for v in values],"loss_comparison":"only within this support pattern"})
    details={"status":"unavailable" if not used else "degraded" if len(used)<target else "selected","distinct_supported_sources":len(used),"requested_finalists":target,"invalid_or_nonfinite_records":len(records)-len(eligible),"competitive_limit":None,"third_fallback_to_next_supported":False,"third_pool":[],"evidence_groups":group_audit,"ordered_record_ids":[v["id"] for v in all_records],"scarcity_filled_from_lower_support":False}
    if not unique_groups:return [],details
    finalists,choice=comparable_finalists(unique_groups[0],config);details.update(choice)
    if len(finalists)<target:
        for group in unique_groups[1:]:
            additions=group[:target-len(finalists)]
            finalists.extend(additions);details["scarcity_filled_from_lower_support"]|=bool(additions)
            if len(finalists)==target:break
    return finalists,details


def finalist_evidence(run):
    """Read saved screen/refinement evidence without writing or scheduling work."""
    run,config,identity=w.run_check(run);root=run/"perspective"
    if (root/"screen/support_manifest.json").exists():verify_native_stage(run,"screen")
    manifest=root/"screen/candidates.json"
    if not manifest.exists():manifest=root/"screen_candidates.json"
    candidates=w.read(manifest) if manifest.exists() else [];records=[];fallback_records=[];excluded=[];limitations=[]
    for c in candidates:
        cid=c["id"];directory=root/"screen/analysis"/cid
        source=selected_source(root,c)
        if not source.exists():excluded.append({"id":cid,"reason":"missing_source_final"});continue
        source_value=w.read(source)
        if not source_value.get("valid") or not valid_vector(source_value.get("x"),config):excluded.append({"id":cid,"reason":"invalid_source_final"});continue
        summary=w.read(directory/"summary.json") if (directory/"summary.json").exists() else {}
        micro=w.read(directory/"microscopy_scores.json") if (directory/"microscopy_scores.json").exists() else {}
        correction=w.read(directory/"correction.json") if (directory/"correction.json").exists() else None
        if correction is not None:check_correction_source(root,c,source_value,correction)
        native_total=next((micro.get(k) for k in ["ranking_total","total","partial_total"] if finite(micro.get(k))),None)
        bias=next((micro.get(k) for k in ["ranking_native_minus_approximation_bias","native_minus_approximation_bias"] if finite(micro.get(k))),None)
        support="complete" if finite(micro.get("total")) and not summary.get("failures") else "partial" if finite(native_total) else "unavailable"
        support_detail=micro.get("support",micro.get("native_support"))
        base={"source_id":cid,"alpha":c["alpha"],"native_support":support,"native_support_detail":support_detail,"native_requested_replicates":micro.get("requested_replicates"),"native_screen_indices":micro.get("indices"),"native_screen_microscopy":micro.get("total"),"native_ranking_microscopy":native_total,"native_failures":summary.get("failures",[])}
        if support!="complete":limitations.append({"id":cid,"native_support":support,"reason":"partial_screen_support" if support=="partial" else "missing_or_nonfinite_screen_support","failures":summary.get("failures",[]),"correction_status":summary.get("correction_status")})
        if finite(source_value.get("loss")):
            fallback_records.append(dict(base,id=cid,x=source_value["x"],source=str(source.relative_to(root)),source_sha256=w.sha(source),selection_score=float(source_value["loss"]),ranking_basis="approximation_source_loss",physical_refined=False,correction=None,approximation_data_loss=source_value.get("data_loss"),approximation_assay_deviance=source_value.get("assay_deviance")))
        correction_available=correction is not None and summary.get("correction_status") not in {"unavailable","invalid","failed"}
        options=[(cid,directory/"corrected_final.json",True,None)]
        for replica in sorted((root/"refinement"/cid).glob("replicate_*")):
            if not replica.is_dir():continue
            saved=replica/"final.json"
            if not saved.exists():saved=replica/"checkpoint.json"
            if not saved.exists():continue
            try:ri=int(replica.name.removeprefix("replicate_"))
            except ValueError:raise w.SetupError("Invalid refinement replica identity")
            options.append(("refined_"+cid+f"_r{ri:03}",saved,False,ri))
        for path in [root/"refinement"/cid/"final.json",root/"candidates"/("refined_"+cid)/"final.json"]:
            if path.exists():options.append(("refined_"+cid,path,False,None));break
        accepted=[]
        if finite(native_total) and finite(bias) and correction_available:
            for label,path,original,replica in options:
                if not path.exists():excluded.append({"id":label,"reason":"missing_corrected_source"});continue
                value=w.read(path)
                if not value.get("valid") or not valid_vector(value.get("x"),config):excluded.append({"id":label,"reason":"invalid_corrected_source"});continue
                if original and not np.allclose(value["x"],source_value["x"],rtol=0.,atol=1e-12):raise w.SetupError("Corrected source vector mismatch")
                if value.get("source_x") is not None:check_correction_source(root,c,source_value,{"source_x":value["source_x"]})
                if not original:
                    if value.get("source_candidate_id",cid)!=cid:raise w.SetupError("Foreign refinement source candidate")
                    if value.get("candidate",{}).get("id",label)!=label:raise w.SetupError("Refinement candidate identity mismatch")
                    if replica is not None or value.get("source_final_sha256"):
                        if value.get("source_final_sha256")!=w.sha(source):raise w.SetupError("Refinement source final changed")
                    if replica is not None or value.get("correction_sha256"):
                        if value.get("correction_sha256")!=w.sha(directory/"correction.json"):raise w.SetupError("Refinement correction changed")
                    if replica is not None:
                        attempt_path=path.parent/"attempt_identity.json"
                        if not attempt_path.exists():excluded.append({"id":label,"reason":"missing_refinement_attempt_identity"});continue
                        attempt=w.read(attempt_path)
                        expected={"candidate_id":label,"source_candidate_id":cid,"refinement_replicate":replica,"source_final_sha256":w.sha(source),"correction_sha256":w.sha(directory/"correction.json")}
                        if any(attempt.get(k)!=v for k,v in expected.items()):raise w.SetupError("Refinement attempt identity changed")
                        check_correction_source(root,c,source_value,{"source_x":attempt.get("source_x")})
                        if value.get("refinement_replicate",replica)!=replica:raise w.SetupError("Refinement replica identity mismatch")
                        if "lower_z" in attempt or "upper_z" in attempt:
                            lower=np.asarray(attempt.get("lower_z"),float);upper=np.asarray(attempt.get("upper_z"),float);point=encode(value["x"],config["perspective"]["bounds"])
                            if lower.shape!=(32,) or upper.shape!=(32,) or not np.isfinite(lower).all() or not np.isfinite(upper).all() or (lower>upper).any() or (point<lower-1e-12).any() or (point>upper+1e-12).any():raise w.SetupError("Refinement vector outside frozen source bounds")
                terms=[value.get("data_loss"),bias,value.get("assay_deviance"),value.get("ridge_penalty")]
                if any(not finite(v) for v in terms):excluded.append({"id":label,"reason":"nonfinite_selection_terms"});continue
                accepted.append(dict(base,id=label,x=value["x"],source=str(path.relative_to(root)),correction=correction,selection_score=sum(terms),ranking_basis="native_corrected_composite" if support=="complete" else "native_partial_corrected_composite",corrected_cohort_microscopy=value["data_loss"],native_image_bias=bias,corrected_assay_deviance=value["assay_deviance"],ridge_penalty=value["ridge_penalty"],physical_refined=not original,refinement_replicate=replica,checkpoint_recovery=path.name=="checkpoint.json",source_sha256=w.sha(path)))
        # A finite native microscopy score remains evidence when a correction or
        # refinement is unavailable. Use the unchanged physical source and its
        # saved accompanying-data terms; never manufacture a correction/bias.
        if not accepted and finite(native_total):
            terms=[native_total,source_value.get("assay_deviance"),source_value.get("ridge_penalty")]
            if all(finite(v) for v in terms):
                accepted.append(dict(base,id=cid,x=source_value["x"],source=str(source.relative_to(root)),source_sha256=w.sha(source),correction=None,selection_score=sum(terms),ranking_basis="native_screen_uncorrected_composite" if support=="complete" else "native_partial_uncorrected_composite",corrected_cohort_microscopy=None,native_image_bias=None,corrected_assay_deviance=source_value["assay_deviance"],ridge_penalty=source_value["ridge_penalty"],physical_refined=False))
            else:excluded.append({"id":cid,"reason":"nonfinite_native_source_selection_terms"})
        records.extend(accepted)
    return {"native_records":records,"approximation_records":fallback_records,"excluded":excluded,"limitations":limitations}


def select_finalists(run):
    run,config,identity=w.run_check(run);root=run/"perspective"
    if (root/"finalists.json").exists():raise w.SetupError("Finalist selection already frozen; no overwrite")
    evidence=finalist_evidence(run)
    records=evidence["native_records"];fallback_records=evidence["approximation_records"];excluded=evidence["excluded"];limitations=evidence["limitations"]
    fallback_used=not bool(records)
    if fallback_used:records=fallback_records
    records.sort(key=lambda v:(v["selection_score"],v["id"]))
    finalists,selection=finalist_choice(records,config)
    order={cid:i for i,cid in enumerate(selection["ordered_record_ids"])};records.sort(key=lambda v:order[v["id"]])
    degraded=len(finalists)<config["perspective"]["conditional"]["finalists"] or fallback_used or any(c["native_support"]!="complete" or "uncorrected" in c["ranking_basis"] for c in finalists)
    for i,c in enumerate(finalists):
        c["finalist_reason"]=("Available finite approximation/source score; native-informed ranking unavailable" if fallback_used else "Available source in evidence-tier order; losses compared within matching support" if selection["scarcity_filled_from_lower_support"] else "Best available native-informed distinct source" if i<2 else "Parameter-diverse competitive third; next available source if none competitive")
    w.write(root/"finalists.json",finalists);w.write(root/"native_informed_ranking.json",records)
    w.write(root/"approximation_fallback_ranking.json",sorted(fallback_records,key=lambda v:(v["selection_score"],v["id"])))
    w.write(root/"audit/finalist_selection.json",{"status":"unavailable" if not finalists else "degraded" if degraded else "selected","degraded":degraded,"selected":[c["id"] for c in finalists],"selected_count":len(finalists),"requested_count":config["perspective"]["conditional"]["finalists"],"ranking_basis":"approximation_source_loss" if fallback_used else "native_informed_composite","approximation_fallback_used":fallback_used,"scores_fabricated":False,"excluded":excluded,"limitations":limitations,"selection":selection,"run_id":identity["run_id"]})
    prepare_native(run,"final_validation",finalists)
    return finalists
