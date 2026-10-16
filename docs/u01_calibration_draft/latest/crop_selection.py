"""Choose display windows against each field's own full-field summaries only.

These descriptive presentation scores never compare observations with simulations
and never enter the fitted objective. Inputs are saved prepared/native geometry.
"""
import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from skimage.morphology import disk


POLICY = {
    "area_fraction": .25,
    "shape_yx": [550, 700],
    "grid": "11 equally spaced integer origins per axis: x=0,70,...,700; y=0,55,...,550",
    "comparison": "Each crop against its own complete field; never observed-versus-simulated agreement",
    "groups": ["density", "dead_fraction", "coverage", "gap", "organization", "relative_area", "living_high_fraction"],
    "weights": "Equal weights over available groups; observed living_high_fraction omitted",
    "scales": {"log_density": float(np.log(1.25)), "dead_fraction": .05,
               "coverage": .05, "log_gap": float(np.log(1.25)), "organization": .10,
               "log_area_quantiles": .20, "living_high_fraction": .05},
    "tie_break": "Smallest unrounded score, then squared distance from centered origin, then y, then x",
    "organization": "2*sqrt(n/area)*mean(NN distance), excluding focal centers whose NN distance exceeds their distance to the window boundary",
    "area": "10/50/90% log area quantiles, normalized by the full field's mean area; whole-object areas for centers in the window",
    "coverage_gap": "Radius-10 closed envelope; 30px inner margin; stride-4 right-censored KM gap median",
    "annotations": "Reject any observed window intersecting pre-existing presentation annotations",
    "scope": "Display selection only; complete-field fitted statistics, validation and losses are unchanged",
}


def _gap(env, distance, rect):
    x0, y0, x1, y1 = rect
    yy, xx = np.mgrid[y0+30:y1-30:4, x0+30:x1-30:4]
    keep = ~env[yy, xx]
    y, x = yy[keep], xx[keep]
    if not len(x):
        return None
    censor = np.minimum.reduce([x-x0-29, x1-30-x, y-y0-29, y1-30-y]).astype(float)
    d = distance[y, x]
    times, events = np.minimum(d, censor), d <= censor
    order = np.argsort(times)
    times, events = times[order], events[order]
    unique, first = np.unique(times, return_index=True)
    deaths = np.add.reduceat(events.astype(int), first)
    cdf = 1-np.cumprod(1-deaths/(len(times)-first))
    hits = np.flatnonzero(cdf >= .5)
    return float(unique[hits[0]]) if len(hits) else None


def choose_window(geometry, binary, unknown=None, overrides=None):
    h, w = binary.shape
    centers = np.asarray(geometry["centers"])
    areas = np.asarray(geometry["areas"])
    dead = np.asarray(geometry["dead"], dtype=bool)
    high = geometry.get("high")
    high = None if high is None else np.asarray(high, dtype=bool)
    assert centers.shape == (len(areas), 2) and len(dead) == len(areas)
    assert np.all(areas > 0)
    nn = cKDTree(centers).query(centers, k=2)[0][:, 1]
    env = ndi.binary_closing(np.pad(binary, 30, mode="reflect"), structure=disk(10))[30:-30, 30:-30]
    distance = ndi.distance_transform_edt(~env)
    full_mean = float(areas.mean())

    def metrics(rect):
        x0, y0, x1, y1 = rect
        inside = ((centers[:, 0] >= x0) & (centers[:, 0] < x1) &
                  (centers[:, 1] >= y0) & (centers[:, 1] < y1))
        n = int(inside.sum())
        if n < 2:
            return None
        edge_distance = np.minimum.reduce([centers[:, 0]-x0, x1-centers[:, 0],
                                           centers[:, 1]-y0, y1-centers[:, 1]])
        focal = inside & (nn <= edge_distance)
        if not np.any(focal):
            return None
        area = (x1-x0)*(y1-y0)
        gap = _gap(env, distance, rect)
        if gap is None:
            return None
        living = inside & ~dead
        return dict(count=n, density=n/area, dead_count=int((inside & dead).sum()),
                    living_count=int(living.sum()),
                    living_low_count=None if high is None else int((living & ~high).sum()),
                    living_high_count=None if high is None else int((living & high).sum()),
                    dead_fraction=float(dead[inside].mean()),
                    coverage=float(env[y0+30:y1-30, x0+30:x1-30].mean()), gap=gap,
                    organization=float(2*np.sqrt(n/area)*nn[focal].mean()),
                    nn_focal_centers=int(focal.sum()),
                    log_area_quantiles=np.quantile(np.log(areas[inside]/full_mean), [.1, .5, .9]).tolist(),
                    living_high_fraction=None if high is None else float(high[living].mean()) if living.any() else None)

    full = metrics([0, 0, w, h])
    assert full is not None
    if overrides:
        full.update(overrides)
    scales = POLICY["scales"]
    candidates = []
    for y0 in np.linspace(0, h-550, 11).round().astype(int):
        for x0 in np.linspace(0, w-700, 11).round().astype(int):
            rect = list(map(int, [x0, y0, x0+700, y0+550]))
            if unknown is not None and unknown[y0:y0+550, x0:x0+700].any():
                candidates.append(dict(rect=rect, eligible=False, reason="Existing presentation overlay"))
                continue
            value = metrics(rect)
            if value is None:
                candidates.append(dict(rect=rect, eligible=False, reason="Insufficient density/spatial support"))
                continue
            losses = dict(density=(np.log(value["density"]/full["density"])/scales["log_density"])**2,
                          dead_fraction=((value["dead_fraction"]-full["dead_fraction"])/scales["dead_fraction"])**2,
                          coverage=((value["coverage"]-full["coverage"])/scales["coverage"])**2,
                          gap=(np.log(value["gap"]/full["gap"])/scales["log_gap"])**2,
                          organization=((value["organization"]-full["organization"])/scales["organization"])**2,
                          relative_area=float(np.mean(((np.array(value["log_area_quantiles"])-full["log_area_quantiles"])/scales["log_area_quantiles"])**2)))
            if high is not None and value["living_high_fraction"] is not None:
                losses["living_high_fraction"] = ((value["living_high_fraction"]-full["living_high_fraction"])/scales["living_high_fraction"])**2
            score = float(np.mean(list(losses.values())))
            candidates.append(dict(rect=rect, eligible=True, metrics=value, components={k:float(v) for k,v in losses.items()},
                                   score=score, center_distance_squared=float((x0-350)**2+(y0-275)**2)))
    eligible = [r for r in candidates if r["eligible"]]
    assert eligible, "No eligible presentation window"
    selected = min(eligible, key=lambda r:(r["score"], r["center_distance_squared"], r["rect"][1], r["rect"][0]))
    return selected["rect"], dict(full=full, selected=selected, candidates=candidates,
                                 eligible_candidates=len(eligible), policy=POLICY,
                                 metric_weights={k:1/len(selected["components"]) for k in selected["components"]})
