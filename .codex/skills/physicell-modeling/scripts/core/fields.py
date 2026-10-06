import numpy as np
import matplotlib
import xml.etree.ElementTree as ET
from scipy import ndimage as ndi
from scipy.io import loadmat
from skimage.draw import disk
from skimage.segmentation import find_boundaries
from pathlib import Path

def colour_labels(labels, seed):
    """Seeded greedy graph coloring, including neighbours across narrow gaps."""
    ids, inverse = np.unique(labels, return_inverse=True)
    if ids[0] != 0:
        ids=np.r_[0,ids];inverse=inverse+1
    lab = inverse.reshape(labels.shape).astype(np.int32)
    distance, nearest = ndi.distance_transform_edt(lab == 0, return_indices=True)
    expanded = lab[tuple(nearest)]
    expanded[distance > 3] = 0
    pairs = []
    for a, b in ((expanded[:-1], expanded[1:]), (expanded[:, :-1], expanded[:, 1:]),
                 (expanded[:-1, :-1], expanded[1:, 1:]), (expanded[1:, :-1], expanded[:-1, 1:])):
        keep = (a != b) & (a > 0) & (b > 0)
        pairs.append(np.sort(np.column_stack((a[keep], b[keep])), axis=1))
    pairs = np.unique(np.concatenate(pairs), axis=0)
    neighbours = [set() for _ in ids]
    for a, b in pairs:
        neighbours[a].add(b)
        neighbours[b].add(a)
    palette = np.array(['#F3C969', '#80C7E8', '#C596DC', '#7DCEAB', '#F28B82', '#A5B7F0',
                        '#D6D779', '#EBA9CA', '#7EC9C5', '#EFAD75', '#B7D2A0', '#D0B6E8'])
    rgb = np.array([matplotlib.colors.to_rgb(x) for x in palette])
    rng = np.random.default_rng(seed)
    tie = rng.random(len(ids))
    order = sorted(range(1, len(ids)), key=lambda i: (-len(neighbours[i]), tie[i]))
    color = np.full(len(ids), -1, dtype=int)
    for node in order:
        used = {color[n] for n in neighbours[node] if color[n] >= 0}
        choices = [c for c in range(len(rgb)) if c not in used]
        if not choices:
            raise RuntimeError('Color palette exhausted')
        rng.shuffle(choices)
        color[node] = max(choices, key=lambda c: min(np.linalg.norm(rgb[c] - rgb[u]) for u in used)) if used else choices[0]
    assert all(color[a] != color[b] for a, b in pairs)
    lut = np.zeros((len(ids), 3), dtype=np.uint8)
    lut[1:] = np.rint(rgb[color[1:]] * 255).astype(np.uint8)
    out = lut[lab]
    out[find_boundaries(lab, mode='inner')] = 25
    return out, dict(visible_cells=len(ids) - 1, adjacency_edges=len(pairs), coloring_conflicts=0)


def simulated_labels(snapshot, shape, crop_origin):
    CROP_X,CROP_Y=crop_origin
    root = ET.parse(snapshot).getroot()
    labels = {x.text: int(x.attrib['index']) for x in root.findall('.//labels/label')}
    data = loadmat(snapshot.with_name(snapshot.stem + '_cells.mat'))['cells']
    live = data[labels['dead']] == 0
    x = data[labels['position'], live] - CROP_X
    y = data[labels['position'] + 1, live] - CROP_Y
    radius = (3 * data[labels['total_volume'], live] / (4 * np.pi)) ** (1 / 3)
    h, w = shape
    near = (x + radius >= 0) & (x - radius < w) & (y + radius >= 0) & (y - radius < h)
    out = np.zeros(shape, dtype=np.int32)
    best = np.full(shape, np.inf, dtype=np.float32)
    for i, (xx, yy, r) in enumerate(zip(x[near], y[near], radius[near]), 1):
        row, col = disk((yy, xx), r, shape=shape)
        d = ((row - yy) ** 2 + (col - xx) ** 2) / r ** 2
        use = d < best[row, col]
        out[row[use], col[use]] = i
        best[row[use], col[use]] = d[use]
    return out
