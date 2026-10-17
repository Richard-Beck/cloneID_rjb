#!/usr/bin/env python3
"""Rebuild the approved figure from its self-contained figure_data bundle.

No pilot directory, private provenance, raw imaging, scientific engine or scheduler
is needed. Full-field numerical validation and representative crops are preserved.
"""
from pathlib import Path
import os

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"

import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from PIL import Image
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from scipy.special import expit
from scipy.stats import norm
from skimage.draw import disk
from skimage.morphology import disk as morphdisk
from skimage.segmentation import find_boundaries

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT))
from crop_selection import choose_window
from compute_projection import project as project_compute
BUNDLE = OUT / "figure_data"
LOCAL = OUT / ".rebuild"
CONFIG = json.loads((OUT / "config.json").read_text())
REFERENCE = BUNDLE
DATA = json.loads((BUNDLE / "plot_data.json").read_text())
SHAPE = (1100, 1400)
AREA = float(np.prod(SHAPE))
Q = np.arange(.02, 1, .04)
INK, GRAY, HIGHLIGHT = "#263640", "#6e7b83", "#edb844"
LOW, HIGH, ALIVE, DEAD = "#38bdf8", "#f472b6", "#009e73", "#d55e00"
PALETTE = np.array([[0, 0, 0], [56, 189, 248], [244, 114, 182],
                    [213, 94, 0], [0, 158, 115]], np.uint8)
OXYGEN = ["#e63946", "#f77f00", "#e5ba00", "#6bbd43", "#00a6a6",
          "#2389da", "#4655c6", "#a239c8"]
DISPLAY_ARMS = {"O1": "hypoxia 1", "O2": "hypoxia 2"}
DEPENDENCIES = {}
CHECKS = {}
NATIVE = {}
FIELD_GEOMETRY = {}


def track(path, role):
    path = Path(path).resolve()
    if str(path) not in DEPENDENCIES:
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(2**20), b""):
                h.update(block)
        DEPENDENCIES[str(path)] = dict(path=str(path), sha256=h.hexdigest(), role=role)
    return path


def read(path):
    return json.loads(track(path, "saved numerical/provenance JSON").read_text())


def csv(path):
    return pd.read_csv(track(path, "saved numerical CSV"))


def npz(path):
    return np.load(track(path, "saved numerical NPZ"))


def dump(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def clean(ax, grid=True):
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(length=2.4, width=.6, color="#a9b3b9", pad=2)
    ax.set_axisbelow(True)
    if grid:
        ax.grid(axis="y", alpha=.15, lw=.55)


def axes(fig, x, top, width, height):
    fw, fh = fig.get_size_inches()
    return fig.add_axes([x/fw, 1-(top+height)/fh, width/fw, height/fh])


def text(fig, x, top, value, **kwargs):
    fw, fh = fig.get_size_inches()
    return fig.text(x/fw, 1-top/fh, value, va="top", **kwargs)


def heading(fig, x, top, letter, title):
    text(fig, x, top, letter, fontsize=12, fontweight="bold")


def distributions(binary, centers, areas):
    """The unchanged saved-campaign full-field observable operator."""
    h, w = binary.shape
    env = ndi.binary_closing(np.pad(binary, 30, mode="reflect"),
                             structure=morphdisk(10))[30:-30, 30:-30]
    distance = ndi.distance_transform_edt(~env)
    yy, xx = np.mgrid[30:h-30:4, 30:w-30:4]
    keep = ~env[yy, xx]
    y, x = yy[keep], xx[keep]
    censor = np.minimum.reduce([x-29, w-30-x, y-29, h-30-y]).astype(float)
    d = distance[y, x]
    times, events = np.minimum(d, censor), d <= censor
    order = np.argsort(times)
    times, events = times[order], events[order]
    unique, first = np.unique(times, return_index=True)
    deaths = np.add.reduceat(events.astype(int), first)
    cdf = 1-np.cumprod(1-deaths/(len(times)-first))
    hits = np.flatnonzero(cdf >= .5)
    gap = float(unique[hits[0]]) if len(hits) else np.nan
    nn = cKDTree(centers).query(centers, k=2)[0][:, 1] * 2*np.sqrt(len(centers)/AREA)
    return dict(areas=areas, nn=nn, gap_time=unique, gap_cdf=cdf, gap=gap,
                coverage=float(env[30:-30, 30:-30].mean()), ce=float(nn.mean()))


def model(key):
    spec = CONFIG[key]
    record = dict(candidate=dict(id=spec["candidate"]))
    if key == "lineage":
        record.update(simulator_components=DATA["lineage_components"], simulator_data_loss=DATA["lineage_loss"])
    return dict(key=key, record=record, report=dict(assays=DATA["assays"]), status=spec["status"])


def prepare_perspective(m, lineage):
    arrays = npz(BUNDLE / "numerics.npz")
    predicted = arrays["perspective_predictions"]
    assert predicted.shape == (4, 343, 30) and np.isfinite(predicted).all()
    rr = ((predicted-arrays["observed"])/arrays["scales"])**2
    residual = np.stack([rr[:, :, 0], rr[:, :, 1], rr[:, :, 2], rr[:, :, 5:].mean(axis=2),
                         rr[:, :, 3], rr[:, :, 4]], axis=2)
    parts = (residual*arrays["weights"]*np.array([.5, .1, .1, .1, .1, .1])).sum(axis=1).mean(axis=0)
    assert np.allclose(parts, DATA["perspective_components"], rtol=1e-10)
    assert np.isclose(parts.sum(), DATA["perspective_loss"])
    m["native_predictions"] = predicted
    m["latent"] = {key: arrays[key] for key in arrays.files if key.startswith(("trace_", "latent_"))}
    m["episode_index"] = DATA["episode_index"]
    m["episodes"] = DATA["episodes"]
    byid = {e["episode_id"]: e for e in m["episodes"]}
    index = {e: i for i, e in enumerate(m["episode_index"])}
    errors = []
    for eid, ep in byid.items():
        if ep["parent_episode_id"] is None:
            continue
        i, parent = index[eid], index[ep["parent_episode_id"]]
        inherited = np.interp(ep["parent_transfer_time_days"], m["latent"][f"trace_{parent}"][:, 0],
                              m["latent"][f"latent_{parent}"])
        errors.append(abs(float(m["latent"][f"latent_{i}"][0])-inherited))
    assert max(errors) < 1e-10
    CHECKS.update(perspective_replicates=4, perspective_microscopy_loss=float(parts.sum()),
                  perspective_full_support_score_reconstructed=True,
                  perspective_max_latent_inheritance_error=max(errors),
                  perspective_frozen_curves_verified=True,
                  perspective_probe_support=dict(completed=127, requested=128),
                  perspective_main_field_support=dict(completed=472, requested=472),
                  perspective_validated_joint_score_claimed=False)


def native(m, row, stats=False):
    cache_key = (m["key"], int(row.row))
    if cache_key in NATIVE and (not stats or NATIVE[cache_key][2] is not None):
        return NATIVE[cache_key]
    name = f"{m['key']}_{int(row.row)}"
    arrays = npz(BUNDLE / "cells.npz")
    cells = arrays[name + "_xyzv"]
    dead = arrays[name + "_dead"]
    if m["key"] == "perspective":
        state = arrays[name + "_state"].astype(int)
        assert np.isin(state, [0, 1]).all()
    else:
        state = np.full(len(cells), 0 if row.group == "2N" else 1)
    x, y = cells[:, 0]+700, cells[:, 1]+550
    radius = (3*cells[:, 2]/(4*np.pi))**(1/3)
    h, w = SHAPE
    near = (x+radius >= 0) & (x-radius < w) & (y+radius >= 0) & (y-radius < h)
    inside = (x >= 0) & (x < w) & (y >= 0) & (y < h)
    labels = np.zeros(SHAPE, np.int32)
    best = np.full(SHAPE, np.inf, np.float32)
    for i, (xx, yy, rr) in enumerate(zip(x[near], y[near], radius[near]), 1):
        iy, ix = disk((yy, xx), rr, shape=SHAPE)
        dist = ((iy-yy)**2+(ix-xx)**2)/rr**2
        keep = dist < best[iy, ix]
        labels[iy[keep], ix[keep]] = i
        best[iy[keep], ix[keep]] = dist[keep]
    rgb = PALETTE[np.r_[0, np.where(dead[near], 3, state[near]+1)][labels]]
    edge = find_boundaries(labels, mode="inner") & (labels > 0)
    rgb[edge] = (rgb[edge]*.42).astype(np.uint8)
    FIELD_GEOMETRY[cache_key] = dict(centers=np.column_stack([x[inside], y[inside]]),
         areas=np.pi*radius[inside]**2, dead=dead[inside], high=state[inside] == 1, binary=labels > 0,
         source="Bundled native centers, projected disk areas and living/dead state labels")
    counts = dict(alive=int((inside & ~dead).sum()), dead=int((inside & dead).sum()),
                  alive_nonWGD=int((inside & ~dead & (state == 0)).sum()),
                  alive_WGD=int((inside & ~dead & (state == 1)).sum()))
    info = DATA["native"][name]
    assert counts == info["center_counts"]
    assert abs(info["actual_minutes"]-info["requested_minutes"]) <= .500001
    assert abs(info["requested_minutes"]/1440-row.time_days) < 1e-8
    predicted = npz(BUNDLE / "numerics.npz")[m["key"] + "_predictions"]
    assert np.allclose(np.log1p([counts["alive"]+counts["dead"], counts["dead"]]),
                       predicted[0, int(row.row), :2], rtol=1e-11, atol=1e-11)
    ss = distributions(labels > 0, np.column_stack([x[inside], y[inside]]),
                       np.pi*radius[inside]**2) if stats else None
    NATIVE[cache_key] = rgb, info, ss
    return NATIVE[cache_key]


def display_fields(m, obs):
    arrays = npz(BUNDLE / "cells.npz")
    fields, records = [], []
    for field in DATA["fields"]:
        case = field["case"]
        row = obs[obs.row.eq(case["row"])].iloc[0]
        panels = [np.asarray(Image.open(track(BUNDLE / f"{case['label']}_{name}.png", "lossless observed display pixels")).convert("RGB"))
                  for name in ["brightfield", "segmentation"]]
        assert panels[0].shape == (550, 700, 3) and panels[1].shape == (1100, 1400, 3)
        prefix = f"observed_{int(row.row)}_"
        geometry = {key: arrays[prefix+key] for key in ["centers", "areas", "dead"]}
        geometry["high"] = None
        proof = field["geometry_provenance"]
        assert len(geometry["centers"]) == proof["count"]
        assert int(geometry["dead"].sum()) == proof["dead_count"]
        ce = float(2*np.sqrt(len(geometry["centers"])/AREA)*cKDTree(geometry["centers"]).query(geometry["centers"], k=2)[0][:, 1].mean())
        assert ce == proof["reconstructed_ce"]
        fields.append(dict(case=case, row=row, observed_panels=panels,
            observed_geometry=geometry, exact_full_spatial=field["exact_full_spatial"], geometry_provenance=proof,
            brightfield_origin_xy=field["brightfield_origin_xy"]))
        records.append(dict(label=case["label"], row=int(row.row), tile=case["tile"], lossless_bundled_display=True))
    CHECKS["observed_display_fields_match_approved_selections"] = True
    return fields, records


def plot_lineage(ax, obs, fields, perspective):
    import re
    episodes = obs.sort_values("row").drop_duplicates("episode_id").set_index("episode_id")
    edges = pd.DataFrame(DATA["edges"])
    cmap = ListedColormap(OXYGEN)
    normed = BoundaryNorm([0, .05, .15, .25, .4, .75, 1.5, 10, 25], cmap.N)
    xy, external = {}, []
    for ep, r in episodes.iterrows():
        base = 4.1 if r.group == "2N" else .25
        y = base+dict(control=1., O1=0., O2=-1.)[r.arm]
        xy[ep] = (0, base) if "_dp_seed" in ep else (int(re.search(r"_A(\d+)_seed", ep).group(1)), y)
    for _, edge in edges.iterrows():
        if edge.child_episode_id not in xy:
            continue
        if edge.parent_episode_id not in xy:
            child = episodes.loc[edge.child_episode_id]
            xy[edge.parent_episode_id] = (-1.2, 4.1 if child.group == "2N" else .25)
            external.append(edge.parent_episode_id)
        a, b = xy[edge.parent_episode_id], xy[edge.child_episode_id]
        ax.plot([a[0], b[0]], [a[1], b[1]], color="#b5bec4", lw=.6, zorder=1)
    for ep, r in episodes.iterrows():
        ax.scatter(*xy[ep], c=[float(r.oxygen)], cmap=cmap, norm=normed, s=13,
                   edgecolor="white", lw=.3, zorder=3)
    for ep in external:
        ax.scatter(*xy[ep], s=13, color="#a6b0b8", zorder=3)
    markers = pd.DataFrame(DATA["markers"])
    for _, assay in markers.iterrows():
        ax.scatter(*xy[assay.marked_episode_id], marker="D", s=28, facecolor="none",
                   edgecolor=INK, lw=.75, zorder=4)
    for field in fields:
        case = field["case"]
        x, y = xy[case["episode_id"]]
        ax.scatter(x, y, s=48, facecolor="none", edgecolor=INK, lw=.9, zorder=5)
        ax.annotate(case["label"], (x, y), xytext=(0, 6), textcoords="offset points",
                    ha="center", fontsize=6.5, fontweight="bold")
    x, y = xy[CONFIG["cost_example"]["episode_id"]]
    ax.add_patch(Rectangle((x-.44, y-.36), .88, .72, facecolor=HIGHLIGHT,
                           edgecolor=HIGHLIGHT, alpha=.4, lw=.9, zorder=2))
    ax.annotate("E / F2", (x, y), xytext=(15, -13), textcoords="offset points",
                ha="left", fontsize=6.5, fontweight="bold",
                arrowprops=dict(arrowstyle="-", lw=.7, color=INK))
    for group, base in [("2N", 4.1), ("4N", .25)]:
        ax.text(-2.8, base, group, fontsize=8, fontweight="bold", va="center")
        for arm, dy in [("control", 1), ("O1", 0), ("O2", -1)]:
            ax.text(24.7, base+dy, DISPLAY_ARMS.get(arm, arm), va="center", fontsize=6.4)
    ax.set_xlim(-3.2, 26.4)
    ax.set_ylim(-1.1, 5.65)
    ax.set_xticks([0, 6, 12, 18, 24], ["founder", "6", "12", "18", "24"])
    ax.set_xlabel("Passage", labelpad=3)
    ax.set_yticks([])
    ax.spines[["top", "left", "right"]].set_visible(False)
    handles = [Line2D([], [], marker="o", ls="", color=c, markersize=3,
                       label=f"{o:g}%") for c, o in zip(OXYGEN, [0, .1, .2, .3, .5, 1, 2, 20.5])]
    oxygen_legend = ax.legend(handles=handles, ncol=8, frameon=False, loc="center",
                              bbox_to_anchor=(.53, .49), fontsize=6, handletextpad=.15,
                              columnspacing=.4, borderpad=.1)
    ax.add_artist(oxygen_legend)
    ax.legend(handles=[Line2D([], [], ls="", marker="o", markersize=5,
                              markerfacecolor="none", markeredgecolor=INK, label="F snapshot"),
                       Line2D([], [], ls="", marker="D", markersize=4,
                              markerfacecolor="none", markeredgecolor=INK, label="Karyotype proxy")],
              loc="upper right", bbox_to_anchor=(.93, 1.16), ncol=2, frameon=False,
              fontsize=6, handletextpad=.3, columnspacing=.8)


def plot_histogram(ax, perspective):
    d = pd.DataFrame(dict(chromosome_count=DATA["chromosomes"]))
    d["source_cell_id"] = np.arange(len(d))
    d["current_high_state"] = (d.chromosome_count > 66).astype(int)
    assert len(d) == 220 and not d.source_cell_id.duplicated().any()
    assert np.array_equal(d.current_high_state.to_numpy(), (d.chromosome_count > 66).astype(int))
    bins = np.arange(39.5, 104.5, 2)
    for state, color, name in [(0, LOW, "2N"), (1, HIGH, "4N")]:
        ax.hist(d.loc[d.current_high_state.eq(state), "chromosome_count"], bins=bins,
                color=color, label=name, rwidth=.93, edgecolor="white", linewidth=.35)
    ax.set(xlim=(39, 104), xlabel="Chromosomes per cell", ylabel="Cells")
    ax.set_xticks([40, 60, 80, 100])
    ax.legend(frameon=False, fontsize=7, loc="upper right", handlelength=1, borderpad=.1)
    clean(ax)
    CHECKS["histogram_cells"] = len(d)


def cost_data(lineage, obs):
    row = obs[obs.row.eq(CONFIG["cost_example"]["row"])].iloc[0]
    rows = obs[obs.episode_id.eq(row.episode_id)].sort_values("time_days")
    frozen = npz(BUNDLE / "numerics.npz")
    old = frozen
    sets = []
    for i in range(4):
        ss = {key: old[f"Data_{i}_{key}"] for key in ["areas", "gap_time", "gap_cdf", "nn"]}
        ss["gap"] = float(ss["gap_time"][np.flatnonzero(ss["gap_cdf"] >= .5)[0]])
        ss["ce"] = float(ss["nn"].mean())
        sets.append(ss)
    areas = np.concatenate([s["areas"] for s in sets])
    expected = frozen["observed"][int(row.row)]
    observed = np.r_[np.mean(np.log([s["gap"] for s in sets])),
                     np.mean([s["ce"] for s in sets]), np.quantile(np.log(areas/areas.mean()), Q)]
    assert np.allclose(observed, expected[3:], rtol=1e-10, atol=1e-10)
    rgb, info, ss = native(lineage, row, stats=True)
    predicted = frozen["lineage_predictions"]
    counts = np.expm1(predicted[:, rows.row.to_numpy(int), :2]).mean(axis=0)
    assert np.all(counts[:, 0] >= counts[:, 1])
    # Schema check uses total, then dead on the linear count scale.
    vector = np.r_[np.log1p(info["center_counts"]["alive"]+info["center_counts"]["dead"]),
                   np.log1p(info["center_counts"]["dead"]), ss["coverage"],
                   np.log(max(ss["gap"], 1)), ss["ce"],
                   np.quantile(np.log(ss["areas"]/ss["areas"].mean()), Q)]
    assert np.allclose(vector, predicted[0, int(row.row)], rtol=1e-10, atol=1e-10)
    p = predicted.copy()
    o = frozen["observed"].copy()
    p[:, :, 3] = np.maximum(p[:, :, 3], 0)
    o[:, 3] = np.maximum(o[:, 3], 0)
    rr = ((p-o)/frozen["scales"])**2
    residual = np.stack([rr[:, :, 0], rr[:, :, 1], rr[:, :, 2], rr[:, :, 5:].mean(axis=2),
                         rr[:, :, 3], rr[:, :, 4]], axis=2)
    coefficients = np.array([.5, .1, .1, .1, .1, .1])
    parts = (residual*frozen["weights"]*coefficients).sum(axis=1).mean(axis=0)
    assert np.allclose(parts, lineage["record"]["simulator_components"], rtol=1e-10)
    assert np.isclose(parts.sum(), lineage["record"]["simulator_data_loss"])
    CHECKS.update(cost_example_observed_spatial_operator_matches_saved=True,
                  cost_example_simulator_total_dead_vector_matches_saved=True,
                  accepted_lineage_full_support_score_reconstructed=True,
                  component_coefficients=coefficients.tolist(), replicate_count=len(predicted),
                  illustrative_spatial_replicate=0, spatial_observed_fields=4,
                  statistics_computed_on_crop=False)
    pd.DataFrame(dict(time_days=rows.time_days, observed_total=rows.total_count,
                      observed_dead=rows.dead_count, predicted_total=counts[:, 0],
                      predicted_dead=counts[:, 1])).to_csv(LOCAL / "example_counts.csv", index=False)
    return dict(row=row, rows=rows, counts=counts, observed_sets=sets, simulator=ss,
                observed_coverage=expected[2], snapshot=rgb, native_info=info, parts=parts)


def plot_cost_example(fig, data):
    # The cost example is the narrow right-hand column spanning both upper rows.
    # Counts and coverage plus three CDFs illustrate six components in five facets.
    layouts = [("Total / dead count", .58, .65), ("Coverage", 1.63, .30),
               ("Relative cell area", 2.27, .36), ("Background gap", 3.00, .36),
               ("Organization", 3.73, .36)]
    aa = [axes(fig, 8.98, top, 1.18, height) for _, top, height in layouts]
    count, coverage, area, gap, organization = aa
    row, rows, counts = data["row"], data["rows"], data["counts"]
    count.plot(rows.time_days, counts[:, 0], color=GRAY, lw=1.0, ls="--")
    count.plot(rows.time_days, counts[:, 1], color=GRAY, lw=1.0, ls="--")
    count.plot(rows.time_days, rows.total_count, ls="", marker="o", ms=2.7, color=INK)
    count.plot(rows.time_days, rows.dead_count, ls="", marker="s", ms=2.5, color=INK, markerfacecolor="white")
    count.axvline(row.time_days, color=HIGHLIGHT, lw=3.3, alpha=.5, zorder=0)
    count.annotate("F2", (row.time_days, data["rows"].total_count.iloc[-1]), xytext=(3, -4),
                   textcoords="offset points", fontsize=6, fontweight="bold")
    count.text(.83, .55, "total", transform=count.transAxes, ha="right", fontsize=5.5)
    count.text(.83, .16, "dead", transform=count.transAxes, ha="right", fontsize=5.5)
    count.set(xlabel="Days since seeding", ylabel="Cells / field", ylim=(0, None))
    count.set_xticks([0, 3, 5])
    coverage.plot([0, 1], [data["observed_coverage"], data["simulator"]["coverage"]],
                   color=GRAY, lw=.7, ls="--", zorder=1)
    coverage.scatter([0], [data["observed_coverage"]], marker="o", s=13, color=INK, zorder=3)
    coverage.scatter([1], [data["simulator"]["coverage"]], marker="o", s=13,
                      facecolor="white", edgecolor=INK, lw=.9, zorder=3)
    coverage.set(xticks=[0, 1], xticklabels=["Obs.", "PC"], ylim=(0, 1.02),
                 xlim=(-.5, 1.5), ylabel="Fraction")
    coverage.set_yticks([0, 1])
    sets = [(data["observed_sets"], INK, "-"), ([data["simulator"]], GRAY, "--")]
    gx = np.unique(np.r_[0, np.concatenate([s["gap_time"] for ss, _, _ in sets for s in ss])])
    nx = np.linspace(0, 4, 400)
    for ss, color, style in sets:
        ar = np.concatenate([s["areas"] for s in ss])
        area.step(np.sort(np.log(ar/ar.mean())), np.arange(1, len(ar)+1)/len(ar), where="post",
                  color=color, ls=style, lw=1)
        curves = []
        for s in ss:
            ii = np.searchsorted(s["gap_time"], gx, side="right")-1
            curves.append(np.where(ii >= 0, s["gap_cdf"][np.maximum(ii, 0)], 0))
        gap.step(gx, np.mean(curves, axis=0), where="post", color=color, ls=style, lw=1)
        gap.axvline(np.exp(np.mean(np.log([max(s["gap"], 1) for s in ss]))),
                    color=color, ls=style, lw=.55, alpha=.7)
        curves = [np.searchsorted(np.sort(s["nn"]), nx, side="right")/len(s["nn"]) for s in ss]
        organization.plot(nx, np.mean(curves, axis=0), color=color, ls=style, lw=1)
        organization.axvline(np.mean([s["ce"] for s in ss]), color=color, ls=style, lw=.55, alpha=.7)
    area.set(xlim=(-3, 2), xlabel="log(area / mean)", ylabel="Cell CDF", ylim=(0, 1.02))
    gap.set(xlim=(0, 100), xlabel="Gap distance (px)", ylabel="KM CDF", ylim=(0, 1.02))
    organization.set(xlim=(.4, 3.1), xlabel="Scaled NN distance", ylabel="Cell CDF", ylim=(0, 1.02))
    area.set_xticks([-2, 0, 2])
    gap.set_xticks([0, 50, 100])
    organization.set_xticks([1, 2, 3])
    for ax in [area, gap, organization]:
        ax.set_yticks([0, 1])
    for ax, (title, _, _) in zip(aa, layouts):
        clean(ax)
        ax.tick_params(labelsize=5.8)
        ax.set_xlabel(ax.get_xlabel(), fontsize=6.1, labelpad=2)
        ax.set_ylabel(ax.get_ylabel(), fontsize=6.1, labelpad=2)
        ax.set_title("")
        ax.set_gid("E_cost_facet")
    legend = fig.legend(handles=[Line2D([], [], color=INK, lw=1, marker="o", ms=2.2, label="Observed"),
                                 Line2D([], [], color=GRAY, lw=1, ls="--", label="PhysiCell")],
                        bbox_to_anchor=(8.62/11.5, 1-.32/fig.get_size_inches()[1]),
                        loc="upper left", frameon=False, ncol=2, fontsize=5.8,
                        handlelength=1.1, columnspacing=.5, handletextpad=.3, borderpad=0)
    legend.set_gid("E_common_legend")
    text(fig, 8.45, 4.48, "Weights: total 0.5; others 0.1.", fontsize=5.9)
    count.set_ylabel("Total / dead\ncells per field", fontsize=6.1)
    coverage.set_ylabel("Coverage", fontsize=6.1)
    area.set_ylabel("Area CDF", fontsize=6.1)
    gap.set_ylabel("Gap CDF", fontsize=6.1)
    organization.set_ylabel("NN CDF", fontsize=6.1)


def image_panel(ax, array, crop=True, saved_bar=False, highlight=False, crop_rect=None):
    if crop:
        assert crop_rect is not None
        x0, y0, x1, y1 = crop_rect
        if array.shape[:2] == (550, 700):
            assert (x1-x0, y1-y0) == (700, 550)
            shown = array  # Exact approved brightfield crop; origin verified against full-mask selection.
        else:
            shown = array[y0:y1, x0:x1]
    else:
        shown = array
    h, w = shown.shape[:2]
    ax.imshow(shown, interpolation="nearest")
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.axis("off")
    if crop or not saved_bar:
        bar = CONFIG["scale_bar_pixels_cropped" if crop else "scale_bar_pixels_full"]
        xend, ypos = w*.94, h*.93
        ax.plot([xend-bar, xend], [ypos, ypos], color="white", lw=1.5, solid_capstyle="butt")
        ax.text(xend-bar/2, ypos-h*.035, f"{bar} px", color="white", ha="center", va="bottom",
                fontsize=4.6, bbox=dict(facecolor="black", edgecolor="none", alpha=.65, pad=.5))
    if highlight:
        frame = Rectangle((3, 3), w-6, h-6, fill=False, edgecolor=HIGHLIGHT, lw=1.6)
        frame.set_gid("cost_example_frame")
        ax.add_patch(frame)


def plot_compute(ax, lineage, perspective):
    projection = project_compute(BUNDLE / "compute_inputs.json", read)
    used = [projection[key]["used_cpu_hours"] for key in ["lineage", "perspective"]]
    estimated = [projection[key]["projected_cpu_hours"] for key in ["lineage", "perspective"]]
    for i, (u, a) in enumerate(zip(used, estimated)):
        ax.bar(i, a, width=.65, facecolor="white", edgecolor=GRAY, hatch="///", lw=.7)
        ax.bar(i, u, width=.43, color="#536977", edgecolor="white", lw=.4)
        ax.text(i, a*1.08, f"{a/1000:.0f}k", ha="center", va="bottom", fontsize=5.6)
        ax.text(i, u/1.12, f"{u:.0f}", ha="center", va="top", fontsize=5.5, color="white")
    ax.set(yscale="log", ylim=(10, max(estimated)*5), xlim=(-.4, 1.4), xticks=[0, 1], xticklabels=["Lineage-guided", "Perspective guided"], ylabel="CPU-hours (log)")
    ax.set_yticks([10, 100, 1000, 10000, 100000], ["10", "100", "1k", "10k", "100k"])
    ax.minorticks_off()
    ax.tick_params(axis="x", labelsize=5.3)
    ax.legend(handles=[Rectangle((0, 0), 1, 1, color="#536977", label="Used"),
                       Rectangle((0, 0), 1, 1, facecolor="white", edgecolor=GRAY, hatch="///", label="PC-only est.")],
              fontsize=5.3, loc="upper left", frameon=False, handlelength=.8, handletextpad=.35, borderpad=.1)
    clean(ax)
    ax.text(.5, -.25, "Same objective-call budget",
            transform=ax.transAxes, ha="center", fontsize=5.8)
    CHECKS["compute_scope"] = "Measured full campaign TotalCPU versus conditional fixed-call-budget PhysiCell-only estimate; no allocations"
    CHECKS["compute_projection_method"] = projection["method"]
    dump(LOCAL / "compute.json", projection)


def plot_fractions(aa, perspective):
    saved = perspective["latent"]
    index = perspective["episode_index"]
    episodes = perspective["episodes"]
    byid = {r["episode_id"]: r for r in episodes}
    assays = perspective["report"]["assays"]
    exports = []
    for ax, founder in zip(aa, ["2N", "4N"]):
        for arm, style in [("O1", "-"), ("O2", "--")]:
            xy = []
            for i, eid in enumerate(index):
                ep = byid[eid]
                if ep["founding_group"] != founder or ep["arm"] not in [arm, "common"]:
                    continue
                trace = saved[f"trace_{i}"]
                latent = saved[f"latent_{i}"]
                if ep["arm"] == "common":
                    xy.append((0., float(expit(np.interp(ep["duration_days"], trace[:, 0], latent)))))
                else:
                    passage = int(eid.split("_A")[1].split("_")[0])
                    keep = trace[:, 0] <= ep["duration_days"]
                    tt = np.r_[trace[keep, 0], ep["duration_days"]]
                    xx = passage-1+tt/ep["duration_days"]
                    yy = expit(np.interp(tt, trace[:, 0], latent))
                    xy.extend(zip(xx, yy))
            xy = np.array(sorted(xy))
            ax.plot(xy[:, 0], xy[:, 1], color=INK, lw=1.05, ls=style)
        ax.axhline(0 if founder == "2N" else 1, color=GRAY, ls=":", lw=.9)
        for assay in assays:
            if assay["founding_group"] != founder:
                continue
            ep = byid[assay["episode_id"]]
            if ep["arm"] == "C":
                continue
            if ep["arm"] == "common":
                x, arm = 0, "common"
            else:
                x = int(ep["parent_episode_id"].split("_A")[1].split("_")[0])
                arm = ep["arm"]
            k, n = assay["k"], assay["n"]
            high = k/n
            z = norm.ppf(.975)
            center = (high+z*z/(2*n))/(1+z*z/n)
            half = z*np.sqrt(high*(1-high)/n+z*z/(4*n*n))/(1+z*z/n)
            lo, hi = max(0, center-half), min(1, center+half)
            ax.errorbar(x, high, yerr=[[max(0, high-lo)], [max(0, hi-high)]],
                        fmt="o", color=INK, capsize=1.5, ms=2.6, lw=.65)
            fitted_high = assay["frozen_fraction"]
            exports.append(dict(founder=founder, assay=assay["assay_id"], arm=arm, passage=x,
                                observed_4N=high, predicted_4N=fitted_high, n=n))
        ax.set(xlim=(-.8, 24.7), ylim=(-.05, 1.05), xticks=[0, 6, 12, 18, 24],
               yticks=[0, .5, 1], xlabel="Passage")
        ax.text(.04, .92, founder, transform=ax.transAxes, ha="left", va="top", fontsize=6.3,
                bbox=dict(facecolor="white", edgecolor="none", alpha=.8, pad=.2))
        clean(ax)
    aa[0].set_ylabel("Living 4N fraction")
    aa[1].tick_params(labelleft=False)
    aa[0].legend(handles=[Line2D([], [], color=INK, ls="-", lw=1, label=DISPLAY_ARMS["O1"]),
                         Line2D([], [], color=INK, ls="--", lw=1, label=DISPLAY_ARMS["O2"]),
                         Line2D([], [], color=GRAY, ls=":", lw=1, label="Lineage-guided")],
                 fontsize=6, loc="upper left", bbox_to_anchor=(0, .86), frameon=False, handlelength=1.8, borderpad=.1)
    aa[1].legend(handles=[Line2D([], [], color=INK, ls="", marker="o", ms=3, label="Observed")],
                 fontsize=6, loc="lower left", frameon=False, handlelength=1, borderpad=.1)
    pd.DataFrame(exports).to_csv(LOCAL / "hypoxia_assays.csv", index=False)
    CHECKS["fraction_plot_excludes_normoxia"] = True
    CHECKS["fraction_trajectories_monochrome"] = True
    CHECKS["fraction_observation_marker"] = "o"
    CHECKS["fraction_frozen_fit_markers_shown"] = False
    CHECKS["fraction_display_state"] = "Living 4N; direct high-state trajectory and Wilson intervals"
    CHECKS["fraction_trajectory_source"] = "Final-validation frozen cohort latent_i arrays with frozen correction, verified against exact report BLUE curves"
    CHECKS["fraction_passage_coordinate"] = "Episode A(p): p-1+t/duration; assays mark preceding parent harvest; common-root harvest is zero"


def select_display_crops(fields, lineage, perspective):
    records = []
    for field in fields:
        mask = field["observed_panels"][1]
        # Saved mask renders have exactly four biological colors plus black;
        # all other colors belong to the pre-existing scale-bar annotation.
        colors = [(0, 158, 115), (0, 66, 48), (213, 94, 0), (89, 39, 0)]
        binary = np.any(np.stack([np.all(mask == c, axis=2) for c in colors]), axis=0)
        unknown = ~binary & np.any(mask != 0, axis=2)
        annotation = None
        if unknown.any():
            yy, xx = np.where(unknown)
            annotation = [int(xx.min()), int(yy.min()), int(xx.max()+1), int(yy.max()+1)]
            unknown[yy.min():yy.max()+1, xx.min():xx.max()+1] = True
        rect, proof = choose_window(field["observed_geometry"], binary, unknown=unknown,
                                    overrides=field["exact_full_spatial"])
        proof.update(source="Saved prepared pilot TSV plus saved segmentation display; exact full coverage/gap from frozen field measurements",
                     geometry=field["geometry_provenance"], annotation_excluded_xyxy=annotation,
                     observed_genomic_abundance_available=False)
        windows = [rect, rect]
        source_records = [dict(modalities=["Brightfield", "Segmentation"], **proof)]
        for m in [lineage, perspective]:
            native(m, field["row"])
            geo = FIELD_GEOMETRY[(m["key"], int(field["row"].row))]
            rect, proof = choose_window(geo, geo["binary"])
            proof.update(source=geo["source"], genomic_meaning="Founding identity" if m["key"] == "lineage" else "Current genomic state")
            windows.append(rect)
            source_records.append(dict(modalities=[m["key"]], **proof))
        assert windows[0] == windows[1]
        assert all((r[2]-r[0], r[3]-r[1]) == (700, 550) for r in windows)
        assert windows[0][:2] == field["brightfield_origin_xy"], "Recomputed window differs from the bundled brightfield crop"
        field["display_windows"] = windows
        records.append(dict(case=field["case"]["label"], row=int(field["row"].row), sources=source_records))
    dump(LOCAL / "crop_selection.json", records)
    CHECKS.update(crop_selection="Deterministic own-full-field comparison on 11x11 grid; independent native realizations",
                  observed_image_mask_crop_coordinates_identical=True,
                  observed_and_model_crop_coordinates_identical=False,
                  old_observed_annotations_excluded=True,
                  observed_per_cell_source="Saved prepared pilot classification TSV, never a reopened legacy collection",
                  observed_count_checks=True, observed_rounded_centroid_ce_checks=True,
                  observed_area_proxy="Prepared contour areas, not exact fitted pixel areas",
                  observed_genomic_abundance_assigned=False)


def plot_fields(fig, fields, lineage, perspective, compact):
    colnames = ["Brightfield", "Segmentation", "Lineage-guided", "Perspective guided"]
    evidence = []
    for i, field in enumerate(fields):
        row, case = field["row"], field["case"]
        # Four case groups form a 2x2 grid; each keeps all four modalities.
        ytop = 4.84+(i//2)*1.045
        x0 = .58+(i % 2)*5.37
        width, gap = 1.28, .015
        h = width*550/700
        short = row.episode_id.replace("SUM-159_NLS_", "").replace("_seed", "").replace("_", " ")
        short = " ".join(DISPLAY_ARMS.get(token, token) for token in short.split())
        hours = int(np.floor(row.time_days*24+.5))
        day, hour = divmod(hours, 24)
        arrays = list(field["observed_panels"])
        model_info = []
        for m in [lineage, perspective]:
            array, info, _ = native(m, row)
            arrays.append(array)
            model_info.append(info)
        for k, (arr, name) in enumerate(zip(arrays, colnames)):
            ax = axes(fig, x0+k*(width+gap), ytop, width, h)
            ax.set_gid("F_image")
            image_panel(ax, arr, crop=compact, saved_bar=k < 2,
                         highlight=int(row.row) == CONFIG["cost_example"]["row"] and k < 3,
                         crop_rect=field["display_windows"][k] if compact else None)
            modality = ax.text(.035, .04, name, transform=ax.transAxes, ha="left", va="bottom",
                     color="white", fontsize=5.1,
                     bbox=dict(facecolor="black", edgecolor="none", alpha=.72, pad=.7))
            modality.set_gid("F_modality_overlay")
            if k == 0:
                label = ax.text(.035, .975,
                     f"{case['label']}  {short}\n{row.oxygen:g}% O2 | {day}d {hour}h",
                     transform=ax.transAxes, ha="left", va="top", fontsize=5.0, color="white", fontweight="bold",
                     bbox=dict(facecolor="black", edgecolor="none", alpha=.72, pad=.7))
                label.set_gid("F_case_overlay")
        evidence.append(dict(label=case["label"], row=int(row.row), models=model_info,
                             display_crops=field["display_windows"] if compact else [[0, 0, 1400, 1100]]*4))
    return evidence


def render(lineage, perspective, obs, fields, cost, compact=True):
    size = CONFIG["figure_size_inches" if compact else "alternative_size_inches"]
    fig = plt.figure(figsize=size, facecolor="white")
    heading(fig, .35, .14, "A", "")
    heading(fig, .35, 2.43, "B", "")
    heading(fig, 2.93, 2.43, "C", "")
    heading(fig, 4.80, 2.43, "D", "")
    heading(fig, 8.63, .14, "E", "")
    plot_lineage(axes(fig, .65, .42, 7.25, 1.65), obs, fields, perspective)
    plot_histogram(axes(fig, .65, 2.64, 1.90, 1.45), perspective)
    plot_cost_example(fig, cost)
    plot_compute(axes(fig, 3.13, 2.64, 1.45, 1.45), lineage, perspective)
    plot_fractions([axes(fig, x, 2.64, 1.42, 1.45) for x in [5.10, 6.84]], perspective)
    heading(fig, .35, 4.63, "F", "")
    legends = [(ALIVE, "Mask: alive"), (DEAD, "Dead"), (LOW, "Model: 2N"), (HIGH, "Model: 4N")]
    fig.legend(handles=[Rectangle((0, 0), 1, 1, color=c, label=name) for c, name in legends],
               loc="upper right", bbox_to_anchor=(.955, 1-4.61/size[1]), ncol=4, fontsize=6.3,
               frameon=False, handlelength=1, columnspacing=1.1, borderpad=.1)
    evidence = plot_fields(fig, fields, lineage, perspective, compact)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    compute_axis = next(a for a in fig.axes if a.get_ylabel() == "CPU-hours (log)")
    compute_labels = [t.get_window_extent(renderer) for t in compute_axis.get_xticklabels()]
    assert compute_labels[0].xmax < compute_labels[1].xmin
    CHECKS["full_model_cpu_labels_separated"] = True
    image_axes = [a for a in fig.axes if a.get_gid() == "F_image"]
    overlays = [(a, t) for a in image_axes for t in a.texts
                if t.get_gid() in ["F_case_overlay", "F_modality_overlay"]]
    assert len(image_axes) == 16 and len(overlays) == 20
    frames = [(a, p) for a in image_axes for p in a.patches if p.get_gid() == "cost_example_frame"]
    assert len(frames) == 3
    assert [next(t.get_text() for t in a.texts if t.get_gid() == "F_modality_overlay") for a, _ in frames] == ["Brightfield", "Segmentation", "Lineage-guided"]
    assert all(t.get_window_extent(renderer).xmin >= a.get_window_extent(renderer).xmin
               and t.get_window_extent(renderer).xmax <= a.get_window_extent(renderer).xmax
               and t.get_window_extent(renderer).ymin >= a.get_window_extent(renderer).ymin
               and t.get_window_extent(renderer).ymax <= a.get_window_extent(renderer).ymax
               for a, t in overlays)
    assert all(a.get_title() == "" for a in fig.axes)
    assert not any("wgd" in t.get_text().lower() for t in fig.findobj(matplotlib.text.Text))
    CHECKS[f"{'compact' if compact else 'full_field'}_image_labels_inside"] = True
    cost_axes = [a for a in fig.axes if a.get_gid() == "E_cost_facet"]
    assert len(cost_axes) == 5
    assert all(abs(a.get_position().width*size[0]-1.18) < 1e-10 for a in cost_axes)
    assert len(fig.axes) == 26  # A, B, C, two D facets, five E facets, 16 F images.
    CHECKS.update(cost_facet_width_inches=1.18, cost_facets_stacked_vertically=True,
                  separate_snapshot_strip_removed=True, matched_cases=4,
                  matched_case_grid=[2, 2], modalities_per_case=4,
                  matched_image_rows=2, matched_image_columns=8, descriptive_panel_titles=False,
                  highlighted_cost_modalities=["Brightfield", "Segmentation", "Lineage-guided"],
                  perspective_snapshot_highlighted=False, display_branch_names=DISPLAY_ARMS,
                  user_facing_state_labels=["2N", "4N"], footer_removed=True,
                  display_model_labels=["Lineage-guided", "Perspective guided"],
                  panel_mapping=dict(A="Lineage", B="Chromosome histogram", C="Compute",
                                     D="Hypoxia trajectories", E="Cost example", F="Matched fields"))
    stem = CONFIG.get("output_stem", "current") if compact else "alternative_full_fields"
    fig.savefig(OUT / f"{stem}.png", dpi=CONFIG["dpi"], facecolor="white")
    fig.savefig(OUT / f"{stem}.pdf", dpi=CONFIG["dpi"], facecolor="white")
    plt.close(fig)
    return evidence


def render_preview():
    """Package the matching text and current figure into an offline HTML preview."""
    stem = CONFIG.get("output_stem", "current")
    md = track(OUT / "calibration.md", "accompanying figure text and caption").read_text()
    blocks = []
    for paragraph in md.strip().split("\n\n"):
        if paragraph.startswith("!["):
            blocks.append(f'<a href="{stem}.png"><img src="{stem}.png" alt="Baseline pilot multipanel figure"></a>')
            continue
        escaped = html.escape(paragraph.replace("\n", " "))
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        blocks.append(f"<h1>{escaped[2:]}</h1>" if escaped.startswith("# ") else f"<p>{escaped}</p>")
    links = f'<a href="{stem}.png">PNG</a> · <a href="{stem}.pdf">PDF</a> · <a href="calibration.md">Text</a> · <a href="README.md">Source notes</a>'
    alternative = ('<p><a href="alternative_full_fields.png">Complete-field alternative</a> · '
                   '<a href="alternative_full_fields.pdf">Complete-field PDF</a></p>') if CONFIG.get("render_alternative", True) else ""
    document = ('<!doctype html><html lang="en"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>Baseline pilots: SUM-159</title><style>'
                'body{font:16px/1.5 system-ui,sans-serif;color:#263640;max-width:1350px;margin:24px auto;padding:0 20px}'
                'h1{font-size:24px}p{max-width:1100px}a{color:#12607d}'
                'img{display:block;width:100%;height:auto;border:1px solid #d9e0e4;margin:20px 0}'
                '</style><nav>'+links+'</nav>'+"\n".join(blocks)+alternative+'</html>\n')
    (OUT / "preview.html").write_text(document)


def main():
    LOCAL.mkdir(exist_ok=True)
    verify_bundle()
    assert not CONFIG.get("render_alternative", False), "Bundle supports the approved cropped figure only"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7, "axes.labelsize": 7,
                         "xtick.labelsize": 6.5, "ytick.labelsize": 6.5,
                         "text.color": INK, "axes.labelcolor": INK, "axes.edgecolor": "#b5bfc6",
                         "pdf.fonttype": 42})
    lineage, perspective = model("lineage"), model("perspective")
    prepare_perspective(perspective, lineage)
    obs = pd.DataFrame(DATA["observations"])
    fields, observed_evidence = display_fields(lineage, obs)
    cost = cost_data(lineage, obs)
    select_display_crops(fields, lineage, perspective)
    compact = render(lineage, perspective, obs, fields, cost, compact=True)
    full = render(lineage, perspective, obs, fields, cost, compact=False) if CONFIG.get("render_alternative", True) else []
    verify_rebuild(fields, cost)
    render_preview()
    parts = cost["parts"]
    pd.DataFrame({"component": ["total_count", "dead_count", "coverage", "relative_area", "gap", "clark_evans"],
                  "weighted_full_support_contribution": parts}).to_csv(LOCAL / "accepted_lineage_loss_components.csv", index=False)
    CHECKS.update(status="passed", generated_utc=datetime.now(timezone.utc).isoformat(),
                  no_fitting_or_simulation=True, no_raw_microscopy_read=True,
                  saved_observed_display_images=True, historical_archive_required=False,
                  historical_archive_preservation_audit="Separate one-time local promotion manifests; not a rebuild dependency",
                  crop_area_fraction=.25, crop_shape_yx=CONFIG["display_crop_shape_yx"],
                  model_fields_are_independent_realizations=True,
                  lineage_candidate=CONFIG["lineage"]["candidate"],
                  perspective_candidate=CONFIG["perspective"]["candidate"],
                  lineage_replicates=2,
                  expected_figure_pixels=[2760, 1680],
                  approved_area_square_inches=432,
                  compact_area_square_inches=float(np.prod(CONFIG["figure_size_inches"])),
                  compact_area_reduction_fraction=1-float(np.prod(CONFIG["figure_size_inches"]))/432)
    assert Image.open(OUT / f"{CONFIG.get('output_stem', 'current')}.png").size == (2760, 1680)
    dump(LOCAL / "verification.json", CHECKS)
    dump(LOCAL / "fields.json", dict(observed=observed_evidence, compact=compact, full=full,
                                     cost_example=cost["native_info"]))
    for path in [Path(__file__), OUT / "crop_selection.py", OUT / "compute_projection.py", OUT / "config.json"]:
        track(path, "isolated draft source")
    dump(LOCAL / "dependencies.json", [dict(path=str(Path(item["path"]).relative_to(OUT)), sha256=item["sha256"], role=item["role"]) for item in DEPENDENCIES.values()])
    dump(LOCAL / "runtime.json", dict(python=sys.version, executable=sys.executable, threads=1))
    print(OUT / f"{CONFIG.get('output_stem', 'current')}.png")
    if CONFIG.get("render_alternative", True):
        print(OUT / "alternative_full_fields.png")




def verify_bundle():
    manifest = json.loads((BUNDLE / "manifest.json").read_text())
    for entry in manifest["files"]:
        path = BUNDLE / entry["name"]
        assert path.is_file() and path.stat().st_size == entry["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
    CHECKS["bundle_hashes_verified"] = True


def verify_rebuild(fields, cost):
    expected = read(BUNDLE / "expected.json")
    assert np.array_equal(cost["counts"], expected["cost_counts"])
    assert np.array_equal(cost["parts"], expected["cost_components"])
    for field in fields:
        assert field["display_windows"] == expected["crop_rectangles"][field["case"]["label"]]
    rgba = np.asarray(Image.open(OUT / f"{CONFIG.get('output_stem', 'current')}.png").convert("RGBA"))
    pixel_hash = hashlib.sha256(rgba.tobytes()).hexdigest()
    assert pixel_hash == expected["approved_rgba_sha256"], "Rendered pixels differ; use the pinned plotting environment"
    CHECKS.update(approved_png_pixels_identical=True, rgba_sha256=pixel_hash,
                  expected_crop_rectangles_identical=True, expected_cost_counts_components_identical=True)


if __name__ == "__main__":
    main()
