#!/usr/bin/env python3
"""
wind_cfd_import.py - a finished OpenFOAM wind run as a pedestrian-level map.

Reads a ronna job (the results zip from https://ronna.tudelft.nl/openfoam/, or
it unpacked), slices the last time step at 1.5 m and writes
data/processed/wind_<case>.json, wind-speed ratios warped to EPSG:4326 plus a
summary, for the app's Pedestrian wind layer and the Wind & noise card.

    python analysis/wind_noise/wind_cfd_import.py                                    #every case in RESULTS with a download
    python analysis/wind_noise/wind_cfd_import.py baseline ~/Downloads/baseline.zip  #one case from anywhere
    python analysis/wind_noise/wind_cfd_import.py --force                            #skip the STL check

Checks first. The mesh must have a buildings patch, since a job whose STL was
missing still "succeeds" on the empty box (ronna's first baseline did). The STL
in the result must be the one wind_cfd_export.py wrote for this case.

The value at 1.5 m is the mesh cell the plane cuts, as a ParaView slice shows.
Ground cells are ~5 m, so any height under 5 m gives the same map. The ratio is
|U| over the inflow profile (log law from the run's ABLConditions) at each cell
centre. Upwind cells are 20 m and centred at 10 m, so they check the profile
(profile_check) instead. The summary covers the site's open ground and counts
cells above 1.1 and below 0.5. Mesh and U are read from OpenFOAM's own files
with numpy, no ParaView needed.
"""

import gzip
import hashlib
import json
import math
import pathlib
import re
import sys
import zipfile

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "morphology"))
from common.project import ROOT, design_site_polygon, write_processed  #noqa: E402

GEO = ROOT / "cache" / "wind" / "geometry"
CASES = ("baseline", "scenario_a", "scenario_b", "final")
LEVEL_M = 1.5           #pedestrian level of the slice
GRID_M = 2.0            #RD grid the slice is sampled on before warping
MAP_BUFFER_M = 50       #map: design site + this
UPWIND_CLEAR_M = 100    #reference strip ends this far upwind of the first building
MAX_CELL_DIST_M = 10.0  #a grid point farther than this (or half a cell diagonal) from any cut cell has no value
SPEEDUP_RATIO = 1.1     #"faster than open country": 10 % above the inflow, clear of the ~2 % drift an empty domain shows
SHELTER_RATIO = 0.5     #"sheltered": below half the inflow
STEADY_MAX_MS = 0.1     #a non-converged run counts as steady if no cell changed more than this between the last two saves
DEFAULT_WIND_FROM = 225.0  #wind_cfd_export.py's default, used if its meta file is missing


#--- reading a case
class CaseFiles:
    #a ronna result as a zip or a folder; paths are relative to the case root
    def __init__(self, path):
        self.path = path
        if path.is_dir():
            self.names = [p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()]
            self._read = lambda n: (path / n).read_bytes()
        else:
            z = zipfile.ZipFile(path)
            self.names = [n for n in z.namelist() if not n.endswith("/")]
            self._read = z.read
        #the zip may wrap everything in one top folder: find the case root by its mesh
        owner = [n for n in self.names if re.search(r"(^|/)constant/polyMesh/owner(\.gz)?$", n)]
        if not owner:
            sys.exit(f"{path}: no constant/polyMesh/owner, not a reconstructed OpenFOAM case")
        self.prefix = owner[0][: owner[0].index("constant/polyMesh/owner")]

    def has(self, rel):
        return any(self.prefix + rel + s in self.names for s in ("", ".gz"))

    def read(self, rel):
        for s in ("", ".gz"):
            if self.prefix + rel + s in self.names:
                raw = self._read(self.prefix + rel + s)
                return gzip.decompress(raw) if s else raw
        raise FileNotFoundError(rel)

    def latest_time(self):
        #the highest time directory holding a U field, the converged (or last) iteration
        return self.times()[-1]

    def times(self):
        #every time directory holding a U field, in order, without 0 (the initial conditions)
        times = {}
        for n in self.names:
            m = re.fullmatch(re.escape(self.prefix) + r"([0-9.eE+-]+)/U(\.gz)?", n)
            if m:
                try:
                    times[float(m.group(1))] = m.group(1)
                except ValueError:
                    pass
        times.pop(0.0, None)  #0 holds the initial conditions, not a result
        if not times:
            sys.exit(f"{self.path}: no time directory with a U field. Did the solver run?")
        return [times[k] for k in sorted(times)]


def split_header(raw):
    #FoamFile header text and the bytes after it
    i = raw.index(b"FoamFile")
    j = raw.index(b"}", i)
    head = raw[i:j + 1].decode("ascii", "replace")
    return head, raw[j + 1:], "binary" in re.search(r"format\s+(\w+)", head).group(1)


def read_list(body, start, kind, binary):
    #one OpenFOAM list "N ( ... )" at or after start -> (array, end offset); kind: label | scalar | vector
    m = re.compile(rb"(\d+)\s*\(").search(body, start)
    n, pos = int(m.group(1)), m.end()
    width = {"label": 1, "scalar": 1, "vector": 3}[kind]
    if binary:
        dtype = np.int32 if kind == "label" else np.float64
        nbytes = n * width * np.dtype(dtype).itemsize
        arr = np.frombuffer(body, dtype=dtype, count=n * width, offset=pos)
        end = pos + nbytes
        assert body[end:end + 1] == b")", f"binary list of {n} did not end where expected"
    else:
        end = body.index(b")\n", pos) if kind != "vector" else _vector_end(body, pos, n)
        text = body[pos:end].replace(b"(", b" ").replace(b")", b" ")
        arr = np.array(text.split(), dtype=np.int64 if kind == "label" else np.float64)
    return (arr.reshape(-1, 3) if kind == "vector" else arr), end + 1


def _vector_end(body, pos, n):
    #ascii vector lists close with ")" after n "(x y z)" lines; find the closing one
    i = pos
    for _ in range(n):
        i = body.index(b")", i) + 1
    return body.index(b")", i)


def read_faces(raw):
    #faces -> (offsets, point indices); faceCompactList (always for binary) or an ascii faceList
    head, body, binary = split_header(raw)
    if "faceCompactList" in head:
        off, end = read_list(body, 0, "label", binary)
        idx, _ = read_list(body, end, "label", binary)
        return off.astype(np.int64), idx.astype(np.int64)
    m = re.compile(rb"(\d+)\s*\(").search(body)  #ascii faceList: "4(0 1 2 3)" per face
    sizes, idx = [], []
    for k, pts in re.findall(rb"(\d+)\(([\d ]+)\)", body[m.end():]):
        sizes.append(int(k))
        idx.extend(int(p) for p in pts.split())
    return np.concatenate([[0], np.cumsum(sizes)]).astype(np.int64), np.array(idx, dtype=np.int64)


def read_internal_vector(raw):
    #a volVectorField's internalField as (nCells, 3)
    _, body, binary = split_header(raw)
    i = body.index(b"internalField")
    if re.match(rb"internalField\s+uniform", body[i:]):
        sys.exit("U is uniform: the solver wrote no flow field")
    arr, _ = read_list(body, body.index(b">", i) + 1, "vector", binary)  #after "List<vector>"
    return arr


def read_boundary(raw):
    #patch name -> {type, nFaces, startFace}
    text = raw.decode("ascii", "replace")
    out = {}
    for name, block in re.findall(r"\n\s*(\w+)\s*\n\s*\{([^}]*)\}", text[text.index("}", text.index("FoamFile")) + 1:]):
        f = dict(re.findall(r"(\w+)\s+([^;]+);", block))
        out[name] = {"type": f.get("type"), "nFaces": int(f.get("nFaces", 0)), "startFace": int(f.get("startFace", 0))}
    return out


#--- the slice
def cut_cells(case, level):
    #cells the plane z = level cuts -> centres (local x, y), |U|, layer bottom/top, mesh facts
    _, b, binary = split_header(case.read("constant/polyMesh/points"))
    pts, _ = read_list(b, 0, "vector", binary)
    off, idx = read_faces(case.read("constant/polyMesh/faces"))
    _, b, binary = split_header(case.read("constant/polyMesh/owner"))
    owner, _ = read_list(b, 0, "label", binary)
    _, b, binary = split_header(case.read("constant/polyMesh/neighbour"))
    neigh, _ = read_list(b, 0, "label", binary)
    owner, neigh = owner.astype(np.int64), neigh.astype(np.int64)
    n_faces, n_int = len(off) - 1, len(neigh)
    n_cells = int(max(owner.max(), neigh.max() if n_int else 0)) + 1
    assert len(owner) == n_faces, f"owner has {len(owner)} entries for {n_faces} faces"

    starts, counts = off[:-1], np.diff(off)
    fz = pts[idx, 2]
    fzmin, fzmax = np.minimum.reduceat(fz, starts), np.maximum.reduceat(fz, starts)
    fc = np.add.reduceat(pts[idx], starts, axis=0) / counts[:, None]  #face centres

    #a cell spans the z-range of its faces; its centre is the mean of its face centres
    czmin = np.full(n_cells, np.inf); czmax = np.full(n_cells, -np.inf)
    np.minimum.at(czmin, owner, fzmin); np.minimum.at(czmin, neigh, fzmin[:n_int])
    np.maximum.at(czmax, owner, fzmax); np.maximum.at(czmax, neigh, fzmax[:n_int])
    csum = np.zeros((n_cells, 3)); cnt = np.zeros(n_cells)
    np.add.at(csum, owner, fc); np.add.at(csum, neigh, fc[:n_int])
    np.add.at(cnt, owner, 1); np.add.at(cnt, neigh, 1)
    centre = csum / cnt[:, None]

    cut = (czmin <= level) & (czmax > level)
    t = case.latest_time()
    U = read_internal_vector(case.read(f"{t}/U"))
    assert len(U) == n_cells, f"U has {len(U)} values for {n_cells} cells"
    speed = np.linalg.norm(U, axis=1)

    #where the buildings start, from the mesh itself: the first building face upwind
    bnd = read_boundary(case.read("constant/polyMesh/boundary"))
    bp = bnd["buildings"]
    bf = slice(bp["startFace"], bp["startFace"] + bp["nFaces"])
    bld_x0 = float(fc[bf, 0].min())
    return {
        "xy": centre[cut, :2], "speed": speed[cut], "zc": centre[cut, 2],
        "bottom": czmin[cut], "top": czmax[cut],  #each cut cell's z-range
        "n_cells": n_cells, "n_cut": int(cut.sum()), "time": t,
        "domain_x0": float(pts[:, 0].min()), "bld_x0": bld_x0,
    }


def stl_roofs(raw):
    #upward-facing triangles of a binary or ascii STL, (n, 3, 2) in the local frame: the building footprints
    if raw[:5] == b"solid" and b"facet" in raw[:400]:
        v = np.array(re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", raw), dtype=float).reshape(-1, 3, 3)
    else:
        n = int(np.frombuffer(raw, dtype="<u4", count=1, offset=80)[0])
        rec = np.frombuffer(raw, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
                            count=n, offset=84)
        v = rec["v"].astype(float)
    nz = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])[:, 2]
    return v[nz > 1e-9][:, :, :2]


def frame(case_name):
    #site centre (RD) and the ccw rotation wind_cfd_export.py applied, from its meta file
    meta = GEO / f"b_{case_name}.meta.json"
    if meta.exists():
        m = json.loads(meta.read_text())
        return tuple(m["centre_rd"]), float(m["rotation_deg_ccw"]), float(m["wind_from_deg"])
    site = design_site_polygon()
    print(f"  no {meta.relative_to(ROOT)}; using the design-site centroid and wind from {DEFAULT_WIND_FROM:.0f} deg")
    return (site.centroid.x, site.centroid.y), (DEFAULT_WIND_FROM + 90) % 360, DEFAULT_WIND_FROM


def to_local(x, y, centre, alpha_deg):
    #RD -> the CFD frame: shift to the site centre, turn alpha degrees ccw (as wind_cfd_export.to_local)
    a = math.radians(alpha_deg)
    dx, dy = x - centre[0], y - centre[1]
    return math.cos(a) * dx - math.sin(a) * dy, math.sin(a) * dx + math.cos(a) * dy


def to_rd(x, y, centre, alpha_deg):
    #the CFD frame -> RD, the inverse of to_local
    a = math.radians(-alpha_deg)
    return math.cos(a) * x - math.sin(a) * y + centre[0], math.sin(a) * x + math.cos(a) * y + centre[1]


def solver_log(case):
    #did simpleFoam converge, after how many iterations, and with which final residuals
    if not case.has("log.simpleFoam"):
        return {"log": "missing"}
    log = case.read("log.simpleFoam").decode("utf-8", "replace")
    times = re.findall(r"^Time = (\S+)", log, re.M)
    res = {}
    for field, r in re.findall(r"Solving for (\w+), Initial residual = ([0-9.eE+-]+)", log):
        res[field] = float(r)  #the last one wins: the final iteration's initial residual
    return {
        "iterations": int(float(times[-1])) if times else None,
        "converged": "SIMPLE solution converged" in log,
        "final_initial_residuals": {k: float(f"{v:.2e}") for k, v in res.items()},
    }


def abl(case, case_name):
    #the inlet profile the run used, from its 0.orig/include/ABLConditions (else the repo's copy of the case)
    rel = "0.orig/include/ABLConditions"
    if case.has(rel):
        t = case.read(rel).decode("ascii", "replace")
    elif (HERE / "cfd" / case_name / rel).exists():
        t = (HERE / "cfd" / case_name / rel).read_text()
    else:
        sys.exit(f"No {rel} in the result or in analysis/wind_noise/cfd/{case_name}/: the inlet profile is unknown")
    def get(k, default=None):
        m = re.search(rf"^\s*{k}\s+(?:uniform\s+)?([0-9.eE+-]+)", t, re.M)
        return float(m.group(1)) if m else default
    return {"uref_ms": get("Uref"), "zref_m": get("Zref"), "z0_m": get("z0"),
            "d_m": get("d", 0.0), "kappa": get("kappa", 0.41)}


def inflow_speed(z, p):
    #OpenFOAM's atmBoundaryLayer inlet: U(z) = u*/kappa ln((z - d + z0)/z0), u* = kappa Uref / ln((Zref + z0)/z0)
    ustar = p["kappa"] * p["uref_ms"] / np.log((p["zref_m"] + p["z0_m"]) / p["z0_m"])
    return ustar / p["kappa"] * np.log((np.maximum(np.asarray(z) - p["d_m"], 0) + p["z0_m"]) / p["z0_m"])


#--- main
PARAMS = {
    "level": LEVEL_M,  #slice height in m above ground
    "force": "--force" in sys.argv,  #skip the check that the result's STL is this case's
}

RESULTS = [  #one ronna result per case, saved where you put the download
    {"case": "baseline", "result": "cache/wind/results/baseline.zip"},
    {"case": "scenario_a", "result": "cache/wind/results/scenario_a.zip"},
    {"case": "scenario_b", "result": "cache/wind/results/scenario_b.zip"},
    {"case": "final", "result": "cache/wind/results/final.zip"},
]


def run(p):
    #one case: PARAMS merged with one dict from CASES

    from rasterio.crs import CRS
    from rasterio.features import geometry_mask
    from rasterio.transform import from_origin
    from scipy.spatial import cKDTree
    from shapely.geometry import Polygon
    from sky_view_factor import reproject_to_wgs84

    case = CaseFiles(p["result"].expanduser())
    print(f"Wind {p['case']}: {p['result'].name}")

    #1. the run must have meshed buildings
    bnd = read_boundary(case.read("constant/polyMesh/boundary"))
    if bnd.get("buildings", {}).get("nFaces", 0) == 0:
        print(f"  patches: {', '.join(bnd)}", file=sys.stderr)
        sys.exit("No `buildings` patch in this mesh: snappyHexMesh found no STL and meshed the empty "
                 "box (see log.snappyHexMesh). Re-upload the case zip from cfd_scaffold.py and rerun.")

    #2. the STL must be this case's
    if not case.has("constant/triSurface/b_orig.stl"):
        sys.exit("No constant/triSurface/b_orig.stl in the result; cannot tell which case it is.")
    stl = case.read("constant/triSurface/b_orig.stl")  #ronna copies the uploaded STL here
    mine = GEO / f"b_{p['case']}.stl"
    if mine.exists() and hashlib.sha1(stl).digest() != hashlib.sha1(mine.read_bytes()).digest():
        msg = (f"The STL in this result is not {mine.relative_to(ROOT)}: wrong case, or the geometry "
               f"was re-exported since the upload.")
        if not p["force"]:
            sys.exit(msg + " Use --force if you are sure.")
        print("  WARNING: " + msg)
    elif not mine.exists():
        print(f"  {mine.relative_to(ROOT)} not found: cannot check the result is {p['case']} (run wind_cfd_export.py)")

    #3. slice
    c = cut_cells(case, p["level"])
    print(f"  mesh {c['n_cells']:,} cells, time {c['time']}; z = {p['level']} m cuts {c['n_cut']:,} cells")
    if c["n_cut"] == 0:
        sys.exit(f"z = {p['level']} m cuts no cell")

    #4. reference: the inlet profile at each cell's height; checked against the clear upwind cells
    inflow = abl(case, p["case"])
    x_end = c["bld_x0"] - UPWIND_CLEAR_M
    up = (c["xy"][:, 0] < x_end) & (c["xy"][:, 0] > c["domain_x0"] + 20)
    check = None
    if up.sum() >= 10:
        z_up = float(np.median(c["zc"][up]))
        check = {"cells": int(up.sum()), "height_m": round(z_up, 1),
                 "measured_ms": round(float(np.median(c["speed"][up])), 2),
                 "profile_ms": round(float(inflow_speed(z_up, inflow)), 2)}
        check["ratio"] = round(check["measured_ms"] / check["profile_ms"], 3)
        print(f"  profile check: {check['measured_ms']} m/s measured upwind at {z_up:.1f} m, "
              f"{check['profile_ms']} m/s from the inlet profile ({check['ratio']:.0%})")
        if abs(check["ratio"] - 1) > 0.05:
            print("  WARNING: the upwind flow is more than 5 % off the inlet profile; the ratios inherit that")

    #5. sample on an RD grid around the site: the value of the nearest cut cell
    centre, alpha, wind_from = frame(p["case"])
    site = design_site_polygon()
    area = site.buffer(MAP_BUFFER_M)
    xmin, ymin, xmax, ymax = area.bounds
    xmin, ymin = math.floor(xmin / GRID_M) * GRID_M, math.floor(ymin / GRID_M) * GRID_M
    xmax, ymax = math.ceil(xmax / GRID_M) * GRID_M, math.ceil(ymax / GRID_M) * GRID_M
    nx, ny = int((xmax - xmin) / GRID_M), int((ymax - ymin) / GRID_M)
    transform = from_origin(xmin, ymax, GRID_M, GRID_M)
    gx, gy = np.meshgrid(xmin + (np.arange(nx) + 0.5) * GRID_M, ymax - (np.arange(ny) + 0.5) * GRID_M)
    lx, ly = to_local(gx.ravel(), gy.ravel(), centre, alpha)  #grid centres in the CFD frame
    dist, near = cKDTree(c["xy"]).query(np.column_stack([lx, ly]))
    reach = np.maximum(MAX_CELL_DIST_M, 0.75 * (c["top"] - c["bottom"])[near])  #that cell's half diagonal, at least
    speed = c["speed"][near].reshape(ny, nx).astype("float32")
    speed[(dist > reach).reshape(ny, nx)] = np.nan
    zc = c["zc"][near].reshape(ny, nx)  #centre height of the cell each grid point reads
    ref = inflow_speed(zc, inflow).astype("float32")  #undisturbed inflow at that height

    #buildings (the STL's roofs, back in RD) and everything outside the mapped area are no data
    roofs = [Polygon([to_rd(x, y, centre, alpha) for x, y in tri]) for tri in stl_roofs(stl)]
    in_bld = geometry_mask(roofs, (ny, nx), transform, invert=True, all_touched=False)
    outside = geometry_mask([area], (ny, nx), transform, invert=False)
    speed[in_bld | outside] = np.nan
    ratio = speed / ref

    #6. summary over the design site's open ground
    on_site = geometry_mask([site], (ny, nx), transform, invert=True) & np.isfinite(ratio)
    r, s = ratio[on_site], speed[on_site]
    cells_on_site = np.unique(near.reshape(ny, nx)[on_site])  #the cut cells the site's map reads
    layer = (round(float(np.median(c["bottom"][cells_on_site])), 1) + 0.0,  #+0.0: no "-0.0" from snapped cells
             round(float(np.median(c["top"][cells_on_site])), 1))
    z_ref = float(np.median(c["zc"][cells_on_site]))
    print(f"  design site reads cells {layer[0]:.1f}-{layer[1]:.1f} m, centred at {z_ref:.1f} m: "
          f"inflow there {float(inflow_speed(z_ref, inflow)):.2f} m/s")
    summary = {
        "mean": round(float(r.mean()), 2),
        "p95": round(float(np.percentile(r, 95)), 2),
        "exceedance_frac": round(float((r > SPEEDUP_RATIO).mean()), 3),
        "exceedance_ratio": SPEEDUP_RATIO,
        "sheltered_frac": round(float((r < SHELTER_RATIO).mean()), 3),
        "sheltered_ratio": SHELTER_RATIO,
        "mean_ms": round(float(s.mean()), 2),
        "p95_ms": round(float(np.percentile(s, 95)), 2),
        "ref_ms": round(float(inflow_speed(z_ref, inflow)), 2),
        "ref_height_m": round(z_ref, 1),
        "cells": int(r.size),
        "unit": f"open-ground cells of {GRID_M:.0f} m on the design site; ratio = |U| / undisturbed "
                f"inflow at the same height",
    }
    print(f"  design site: mean ratio {summary['mean']}, p95 {summary['p95']}, over {SPEEDUP_RATIO} on "
          f"{summary['exceedance_frac']:.0%}, under {SHELTER_RATIO} on {summary['sheltered_frac']:.0%}")

    #7. warp to WGS84 for draping, and write
    warped, bbox_wgs = reproject_to_wgs84(ratio.astype("float32"), transform, CRS.from_epsg(28992))
    values = [[None if not np.isfinite(v) else round(float(v), 2) for v in row] for row in warped]
    solver = solver_log(case)
    #a run stopped at the iteration cap can still be steady: compare the last two saved fields
    saved = case.times()
    if len(saved) >= 2:
        prev = read_internal_vector(case.read(f"{saved[-2]}/U"))
        last = read_internal_vector(case.read(f"{saved[-1]}/U"))
        dU = np.linalg.norm(last - prev, axis=1)
        solver["change_since"] = saved[-2]
        solver["change_max_ms"] = round(float(dU.max()), 3)
        solver["change_p95_ms"] = round(float(np.percentile(dU, 95)), 3)
        solver["steady"] = bool(dU.max() < STEADY_MAX_MS)
    if not solver.get("converged"):
        how = (f"but the field is steady: at most {solver['change_max_ms']} m/s change since iteration "
               f"{solver['change_since']}" if solver.get("steady") else "and the field is still changing")
        print(f"  NOTE: simpleFoam stopped at {solver.get('iterations')} without reaching its residual target, {how}")
    write_processed(f"wind_{p['case']}.json", indent=None, payload={
        "quantity": "wind_speed_ratio",
        "label": f"Wind-speed ratio at {p['level']:g} m (OpenFOAM, wind from {wind_from:.0f} deg)",
        "unit": "ratio to the undisturbed inflow at the same height",
        "scenario": p["case"],
        "level_m": p["level"],
        "wind_from_deg": wind_from,
        "bbox_rd": [xmin, ymin, xmax, ymax],
        "bbox_wgs84": [round(v, 7) for v in bbox_wgs],
        "shape": list(warped.shape),
        "values": values,
        "summary": summary,
        "inflow": {**inflow, "profile_check": check},
        "solver": {**solver, "time": c["time"], "cells": c["n_cells"]},
        "method": {
            "model": "OpenFOAM v2412 simpleFoam, k-epsilon, ABL inlet (analysis/wind_noise/cfd/)",
            "slice": f"cells cut by z = {p['level']:g} m; on the design site {layer[0]:.1f}-{layer[1]:.1f} m",
            "reference": "the inlet log-law profile (ABLConditions) at each cut cell's centre height; "
                         "checked against the measured upwind flow (inflow.profile_check)",
            "grid_m": GRID_M,
            "map": f"design site + {MAP_BUFFER_M} m; buildings from the case's STL",
            "source": p["result"].name,
        },
        "limitations": [
            "One wind direction and speed; comfort classes (NEN 8100) need the KNMI wind rose.",
            f"Cells near the ground are ~{layer[1] - layer[0]:.0f} m: the slice reads the first "
            "cell layer, so any height inside it gives the same map.",
            "Only the design site's buildings are modelled; shelter from the wider neighbourhood is not.",
        ],
    })
    return 0


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    runs = [{"case": pos[0], "result": pos[1]}] if len(pos) == 2 else RESULTS  #a case and a result on the command line run just that one
    for c in runs:
        assert c["case"] in CASES, c["case"]
        path = pathlib.Path(c["result"]).expanduser()
        path = path if path.is_absolute() else ROOT / path  #RESULTS paths are from the project root
        if not path.exists():
            print(f"{c['case']}: no result at {path}, skipped")
            continue
        run({**PARAMS, **c, "result": path})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
