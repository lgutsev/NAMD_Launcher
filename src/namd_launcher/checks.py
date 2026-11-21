"""Value checks that sit between the stages: what the shape audits do not look at.

Two read-only checks, each writing a JSON verdict (PASS / WARN / FAIL) and a short Markdown report:

``inamd check edges`` -- after the snapshot SCFs, before NAMD. Reads every snapshot folder's EIGENVAL (and PROCAR,
when LORBIT wrote one) and asks whether the NAMD band window is a clean, isolated pair of states across the
trajectory:

- the gap between ``bands.vbm`` and ``bands.cbm`` per frame, its range and the lowest frames;
- how close the nearest band *outside* the window comes to the window's edges (``nac.bmin - 1`` below,
  ``nac.bmax + 1`` above). A neighbour within ``--degenerate-ev`` (default kT at 300 K) means population could go
  there and the window may be too narrow;
- the element make-up of every window band (fractions of the PROCAR ``tot`` column per element) and how far it
  drifts from the first frame's (total-variation distance, 0 = same make-up, 1 = disjoint). A large drift means the
  band changed identity, e.g. a molecular or surface state taking over a band edge;
- for the most changed frames, which atoms carry the weight (index, element, height z in Angstrom), and the weight
  binned by element and z, so a surface molecule can be told from the bulk;
- an inventory of CA-NAC's ``*.npy`` overlap caches (count, bytes) and the stored window, if NAC has run.

``inamd check nac`` -- after ``inamd nac collect``. Reads ``nac/NATXT`` and ``nac/EIGTXT`` and checks the values:

- row counts agree and cover ``namd.nsw``; every value is finite;
- diagonal couplings are ~0 and the matrix is antisymmetric (d_ij = -d_ji), as phase-corrected real NACs must be;
- off-diagonal magnitudes: mean, median, p99, max and the rows of the largest (spikes at band crossings);
- EIGTXT energies agree with the snapshot EIGENVALs (row i against frame i+1, and against the mean of frames i+1
  and i+2, whichever CA-NAC used).

A WARN is not a failure: it means a person reads the report before the next stage. Nothing here writes outside
``<stage>/`` report files, and nothing is ever deleted.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from ._stage import rollup_status
from .cli import _json, register
from .config import Campaign, load_campaign
from .errors import SafetyError

KT_300K_EV = 0.025852
TVD_WARN = 0.25


# --------------------------------------------------------------------------- #
# readers
# --------------------------------------------------------------------------- #
def read_eigenval(path: Path, bands: list[int]) -> dict[int, tuple[float, float | None]]:
    """Energies and occupations of ``bands`` at the first k-point (spin up) of a VASP EIGENVAL."""

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    nb = int(lines[5].split()[2])
    out: dict[int, tuple[float, float | None]] = {}
    want = set(bands)
    for line in lines[8 : 8 + nb]:
        parts = line.split()
        if not parts:
            continue
        b = int(parts[0])
        if b in want:
            out[b] = (float(parts[1]), float(parts[-1]) if len(parts) > 2 else None)
    return out


def read_poscar(path: Path) -> tuple[list[str], list[float]]:
    """Element of every atom and its Cartesian z (Angstrom)."""

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    scale = float(lines[1].split()[0])
    lattice = [[float(v) * scale for v in lines[i].split()[:3]] for i in (2, 3, 4)]
    names, counts = lines[5].split(), [int(v) for v in lines[6].split()]
    i = 7
    if lines[i].strip()[:1] in "sS":
        i += 1
    direct = lines[i].strip()[:1] in "dD"
    elements = [n for n, c in zip(names, counts) for _ in range(c)]
    zs: list[float] = []
    for line in lines[i + 1 : i + 1 + len(elements)]:
        v = [float(t) for t in line.split()[:3]]
        zs.append(sum(v[j] * lattice[j][2] for j in range(3)) if direct else v[2] * scale)
    return elements, zs


_BAND = re.compile(r"\s*band\s+(\d+)\s+#\s*energy\s+(-?[\d.]+)")


def read_procar(path: Path, bands: list[int]) -> dict[int, dict[int, float]]:
    """Per-atom ``tot`` weight of each wanted band at the first k-point / spin (LORBIT 11 PROCAR)."""

    want, out = set(bands), {}
    current: int | None = None
    reading = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            m = _BAND.match(line)
            if m:
                b = int(m.group(1))
                if b in want and b not in out:
                    current, reading = b, False
                    out[b] = {}
                else:
                    current = None
                    if len(out) == len(want) and all(out.values()):
                        break
                continue
            if current is None:
                continue
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "ion":
                reading = True
            elif parts[0] == "tot":
                current, reading = None, False
            elif reading and parts[0].isdigit():
                out[current][int(parts[0]) - 1] = float(parts[-1])
    return out


def _fractions(weights: dict[int, float], elements: list[str]) -> dict[str, float]:
    total = sum(weights.values()) or 1.0
    acc: dict[str, float] = {}
    for i, w in weights.items():
        acc[elements[i]] = acc.get(elements[i], 0.0) + w / total
    return {k: round(v, 4) for k, v in sorted(acc.items())}


def _tvd(a: dict[str, float], b: dict[str, float]) -> float:
    return round(0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b)), 4)


def _folders(campaign: Campaign) -> list[tuple[int, Path]]:
    snap = campaign.stage_dir("snapshots")
    digits = int(campaign.snapshots["digits"])
    return [(k, snap / f"{k:0{digits}d}") for k in range(1, int(campaign.snapshots["nsw"]) + 1)]


def _write(root: Path, name: str, report: dict[str, Any], markdown: str) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    body = {"format": f"namdforge-check-{name}", "schema_version": 1, **report}
    jp, mp = root / f"check_{name}.json", root / f"check_{name}.md"
    jp.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    mp.write_text(markdown, encoding="utf-8")
    return {"json": str(jp), "markdown": str(mp)}


# --------------------------------------------------------------------------- #
# check edges
# --------------------------------------------------------------------------- #
def check_edges(
    campaign: Campaign,
    *,
    degenerate_ev: float = KT_300K_EV,
    tvd_warn: float = TVD_WARN,
    detail: int = 8,
    frames: list[int] | None = None,
) -> dict[str, Any]:
    bands_cfg, nac = campaign.bands, campaign.nac
    vbm, cbm = bands_cfg.get("vbm"), bands_cfg.get("cbm")
    bmin, bmax = nac.get("bmin"), nac.get("bmax")
    if None in (vbm, cbm, bmin, bmax):
        raise SafetyError("check edges needs bands.vbm, bands.cbm, nac.bmin and nac.bmax")
    window = list(range(bmin, bmax + 1))
    look = [bmin - 1, *window, bmax + 1]
    rows: list[dict[str, Any]] = []
    elements: list[str] | None = None
    reference: dict[int, dict[str, float]] = {}
    for k, folder in _folders(campaign):
        ev = folder / "EIGENVAL"
        if not ev.is_file():
            rows.append({"frame": k, "state": "no EIGENVAL"})
            continue
        e = read_eigenval(ev, sorted(set(look + [vbm, cbm])))
        r: dict[str, Any] = {"frame": k, "state": "read"}
        if vbm in e and cbm in e:
            r["gap_eV"] = round(e[cbm][0] - e[vbm][0], 5)
        r["energies"] = {str(b): e[b][0] for b in look if b in e}
        if bmin - 1 in e:
            r["below_eV"] = round(e[bmin][0] - e[bmin - 1][0], 5)
        if bmax + 1 in e:
            r["above_eV"] = round(e[bmax + 1][0] - e[bmax][0], 5)
        pro = folder / "PROCAR"
        if pro.is_file():
            if elements is None:
                elements, _ = read_poscar(folder / "POSCAR")
            weights = read_procar(pro, window)
            comp = {str(b): _fractions(weights.get(b, {}), elements) for b in window}
            r["character"] = comp
            if not reference:
                reference = {b: comp[str(b)] for b in window}
            r["drift"] = {str(b): _tvd(comp[str(b)], reference[b]) for b in window}
        rows.append(r)

    read = [r for r in rows if r["state"] == "read"]
    missing = [r["frame"] for r in rows if r["state"] != "read"]
    gaps = sorted((r["gap_eV"], r["frame"]) for r in read if "gap_eV" in r)
    near_above = [r["frame"] for r in read if r.get("above_eV", 9) < degenerate_ev]
    near_below = [r["frame"] for r in read if r.get("below_eV", 9) < degenerate_ev]
    drifted = sorted(
        ((max(r["drift"].values()), r["frame"]) for r in read if r.get("drift")), reverse=True
    )
    changed = [f for d, f in drifted if d > tvd_warn]

    # where the weight sits in the most changed frames (and any asked for)
    pick = list(dict.fromkeys([*(frames or []), *[f for d, f in drifted[:detail] if d > tvd_warn]]))
    details = []
    for k in pick:
        folder = dict(_folders(campaign)).get(k)
        if folder is None or not (folder / "PROCAR").is_file():
            continue
        el, zs = read_poscar(folder / "POSCAR")
        weights = read_procar(folder / "PROCAR", look)
        entry: dict[str, Any] = {"frame": k}
        for b, w in sorted(weights.items()):
            total = sum(w.values()) or 1.0
            top = sorted(w.items(), key=lambda kv: -kv[1])[:8]
            bins: dict[str, float] = {}
            for i, x in w.items():
                key = f"{el[i]}@{round(zs[i])}"
                bins[key] = bins.get(key, 0.0) + x / total
            entry[str(b)] = {
                "top_atoms": [{"index": i + 1, "element": el[i], "z": round(zs[i], 2), "fraction": round(x / total, 4)}
                              for i, x in top],
                "by_element_z": dict(sorted(((k2, round(v, 4)) for k2, v in bins.items() if v >= 0.02),
                                            key=lambda kv: -kv[1])[:10]),
            }
        details.append(entry)

    cache = _cache_inventory(campaign)
    checks = [
        {"check": "frames read", "status": "PASS" if not missing else "FAIL",
         "detail": f"{len(read)} of {len(rows)}" + (f"; missing {missing[:10]}" if missing else "")},
        {"check": f"band {bmax + 1} within {degenerate_ev} eV above the window", "status": "WARN" if near_above else "PASS",
         "detail": f"{len(near_above)} frames"},
        {"check": f"band {bmin - 1} within {degenerate_ev} eV below the window", "status": "WARN" if near_below else "PASS",
         "detail": f"{len(near_below)} frames"},
        {"check": f"window band make-up drifts > {tvd_warn} from frame 1",
         "status": ("WARN" if changed else "PASS") if drifted else "PENDING",
         "detail": f"{len(changed)} frames" if drifted else "no PROCAR"},
    ]
    status = rollup_status([c["status"] for c in checks if c["status"] != "PENDING"])
    report = {
        "status": status,
        "window": {"bmin": bmin, "bmax": bmax, "vbm": vbm, "cbm": cbm},
        "thresholds": {"degenerate_eV": degenerate_ev, "drift_tvd": tvd_warn},
        "checks": checks,
        "gap_eV": ({"min": gaps[0][0], "max": gaps[-1][0], "mean": round(sum(g for g, _ in gaps) / len(gaps), 5),
                    "lowest": [{"frame": f, "gap_eV": g} for g, f in gaps[:5]]} if gaps else None),
        "near_degenerate_above": near_above,
        "near_degenerate_below": near_below,
        "changed_frames": changed,
        "reference_character": {str(b): v for b, v in reference.items()},
        "details": details,
        "cache": cache,
        "frames": rows,
    }
    md = _edges_md(report)
    report["files"] = _write(campaign.stage_dir("checks"), "edges", report, md)
    return {k: v for k, v in report.items() if k != "frames"}


def _ranges(frames: list[int]) -> str:
    if not frames:
        return "none"
    out, start, prev = [], frames[0], frames[0]
    for f in sorted(frames)[1:] + [None]:  # type: ignore[list-item]
        if f is not None and f == prev + 1:
            prev = f
            continue
        out.append(f"{start}" if start == prev else f"{start}-{prev}")
        if f is not None:
            start = prev = f
    return ", ".join(out)


def _edges_md(r: dict[str, Any]) -> str:
    w = r["window"]
    lines = [f"# Band-edge check: {r['status']}", "",
             f"Window bands {w['bmin']}-{w['bmax']} (VBM {w['vbm']}, CBM {w['cbm']}).", ""]
    lines += ["| check | status | detail |", "|---|---|---|"]
    lines += [f"| {c['check']} | {c['status']} | {c['detail']} |" for c in r["checks"]]
    if r["gap_eV"]:
        g = r["gap_eV"]
        lines += ["", f"Gap {g['min']:.3f}-{g['max']:.3f} eV (mean {g['mean']:.3f}); lowest: "
                  + ", ".join(f"frame {x['frame']} {x['gap_eV']:.3f}" for x in g["lowest"])]
    lines += ["", f"Neighbour above within threshold: {_ranges(r['near_degenerate_above'])}",
              f"Neighbour below within threshold: {_ranges(r['near_degenerate_below'])}",
              f"Make-up changed: {_ranges(r['changed_frames'])}", ""]
    if r["reference_character"]:
        lines += ["Frame-1 make-up: " + "; ".join(f"band {b}: {v}" for b, v in r["reference_character"].items()), ""]
    for d in r["details"]:
        lines.append(f"## Frame {d['frame']}")
        for b, v in d.items():
            if b == "frame":
                continue
            lines.append(f"- band {b}: " + ", ".join(f"{k} {x:.3f}" for k, x in v["by_element_z"].items()))
            lines.append("  top atoms: " + ", ".join(
                f"{a['index']}{a['element']}@{a['z']:.1f} {a['fraction']:.3f}" for a in v["top_atoms"]))
        lines.append("")
    c = r["cache"]
    lines += [f"CA-NAC caches: {c['npy_files']} .npy files, {c['npy_bytes']} bytes; stored window "
              f"{c['stored_window']}; outputs {c['canac_outputs']}", ""]
    return "\n".join(lines)


def _cache_inventory(campaign: Campaign) -> dict[str, Any]:
    snap = campaign.stage_dir("snapshots")
    npys = list(snap.glob("**/*.npy")) if snap.is_dir() else []
    return {
        "npy_files": len(npys),
        "npy_bytes": sum(p.stat().st_size for p in npys),
        "npy_names": sorted({p.name for p in npys})[:12],
        "stored_window": [campaign.nac.get("bmin_stored"), campaign.nac.get("bmax_stored")],
        "canac_outputs": sorted(p.name for p in snap.glob("CA*.txt")) if snap.is_dir() else [],
    }


# --------------------------------------------------------------------------- #
# check nac
# --------------------------------------------------------------------------- #
def _table(path: Path) -> list[list[float]]:
    return [[float(x) for x in line.split()] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_nac(
    campaign: Campaign, *, energy_tol: float = 1e-3, antisym_rel: float = 1e-2, spike_ratio: float = 50.0
) -> dict[str, Any]:
    nac_root = campaign.stage_dir("nac")
    bmin, bmax = campaign.nac["bmin"], campaign.nac["bmax"]
    nb = bmax - bmin + 1
    for name in ("NATXT", "EIGTXT"):
        if not (nac_root / name).is_file():
            raise SafetyError(f"{nac_root / name} is missing: run `inamd nac collect` first")
    na, ei = _table(nac_root / "NATXT"), _table(nac_root / "EIGTXT")
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    ncols, ecols = sorted({len(r) for r in na}), sorted({len(r) for r in ei})
    add("columns", "PASS" if ncols == [nb * nb] and ecols == [nb] else "FAIL",
        f"NATXT {ncols} (expect {nb * nb}), EIGTXT {ecols} (expect {nb})")
    nsw = int(campaign.snapshots["nsw"])
    need = campaign.namd.get("nsw")
    rows_ok = len(na) == len(ei) and len(na) in (nsw - 1, nsw) and (need is None or len(na) >= int(need))
    add("rows", "PASS" if rows_ok else "FAIL",
        f"NATXT {len(na)}, EIGTXT {len(ei)}; snapshots {nsw}; namd.nsw {need}")
    finite = all(math.isfinite(x) for r in na + ei for x in r)
    add("finite", "PASS" if finite else "FAIL", "all values finite" if finite else "NaN or inf present")
    if not (ncols == [nb * nb] and finite and na):
        return _nac_finish(campaign, checks, {})

    diag, off, anti = [], [], []
    for r in na:
        m = [r[i * nb : (i + 1) * nb] for i in range(nb)]
        diag.append(max(abs(m[i][i]) for i in range(nb)))
        for i in range(nb):
            for j in range(i + 1, nb):
                off.append((abs(m[i][j]), len(diag)))
                anti.append(abs(m[i][j] + m[j][i]))
    mags = sorted(x for x, _ in off)
    big = mags[-1] if mags else 0.0
    med = mags[len(mags) // 2] if mags else 0.0
    stats = {
        "offdiag_mean": sum(mags) / len(mags) if mags else 0.0,
        "offdiag_median": med,
        "offdiag_p99": mags[int(0.99 * (len(mags) - 1))] if mags else 0.0,
        "offdiag_max": big,
        "largest": [{"row": row, "value": v} for v, row in sorted(off, reverse=True)[:5]],
        "diag_max": max(diag),
        "antisymmetry_max": max(anti) if anti else 0.0,
    }
    add("diagonal ~ 0", "PASS" if stats["diag_max"] <= antisym_rel * max(big, 1e-30) else "WARN",
        f"max |d_ii| {stats['diag_max']:.3g} against max |d_ij| {big:.3g}")
    rel = stats["antisymmetry_max"] / max(big, 1e-30)
    add("antisymmetric", "PASS" if rel <= antisym_rel else ("WARN" if rel <= 10 * antisym_rel else "FAIL"),
        f"max |d_ij + d_ji| {stats['antisymmetry_max']:.3g} ({rel:.2g} of max |d_ij|)")
    ratio = big / med if med else float("inf")
    add("no isolated spikes", "PASS" if ratio <= spike_ratio else "WARN",
        f"max/median {ratio:.3g} (rows {[x['row'] for x in stats['largest']]})")
    ordered = all(all(r[i] <= r[i + 1] + 1e-9 for i in range(nb - 1)) for r in ei)
    add("EIGTXT ascending", "PASS" if ordered else "WARN", "per row" if ordered else "some rows not ascending")

    frames = []
    for k, folder in _folders(campaign):
        ev = folder / "EIGENVAL"
        if not ev.is_file():
            frames.append(None)
            continue
        e = read_eigenval(ev, list(range(bmin, bmax + 1)))
        frames.append([e[b][0] for b in range(bmin, bmax + 1)] if len(e) == nb else None)
    same, mid = [], []
    for i, r in enumerate(ei):
        a = frames[i] if i < len(frames) else None
        b = frames[i + 1] if i + 1 < len(frames) else None
        if a:
            same.append(max(abs(x - y) for x, y in zip(r, a)))
        if a and b:
            mid.append(max(abs(x - (y + z) / 2) for x, y, z in zip(r, a, b)))
    match = {"compared_rows": len(same), "max_diff_same_frame": max(same) if same else None,
             "max_diff_midpoint": max(mid) if mid else None}
    best = min((x for x in (match["max_diff_same_frame"], match["max_diff_midpoint"]) if x is not None), default=None)
    if best is None:
        add("energies match EIGENVAL", "WARN", "no snapshot EIGENVAL to compare")
    else:
        which = "row i = frame i+1" if best == match["max_diff_same_frame"] else "row i = mean of frames i+1, i+2"
        add("energies match EIGENVAL", "PASS" if best <= energy_tol else ("WARN" if best <= 50 * energy_tol else "FAIL"),
            f"max |diff| {best:.3g} eV over {len(same)} rows ({which})")
        match["alignment"] = which
    stats["energy_match"] = match
    return _nac_finish(campaign, checks, stats)


def _nac_finish(campaign: Campaign, checks: list[dict[str, Any]], stats: dict[str, Any]) -> dict[str, Any]:
    status = rollup_status([c["status"] for c in checks])
    report = {"status": status, "checks": checks, "stats": stats}
    md = [f"# NAC value check: {status}", "", "| check | status | detail |", "|---|---|---|"]
    md += [f"| {c['check']} | {c['status']} | {c['detail']} |" for c in checks]
    if stats:
        md += ["", "Off-diagonal |d|: mean {offdiag_mean:.4g}, median {offdiag_median:.4g}, p99 {offdiag_p99:.4g}, "
               "max {offdiag_max:.4g}".format(**stats), ""]
    report["files"] = _write(campaign.stage_dir("nac"), "nac", report, "\n".join(md) + "\n")
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _frames(text: str | None) -> list[int]:
    return [int(x) for x in text.split(",") if x.strip()] if text else []


def _cmd(args: argparse.Namespace) -> int:
    campaign = load_campaign(args.campaign)
    if args.check_command == "edges":
        out = check_edges(campaign, degenerate_ev=args.degenerate_ev, tvd_warn=args.drift, detail=args.detail,
                          frames=_frames(args.frames))
    else:
        out = check_nac(campaign, energy_tol=args.energy_tol)
    _json({k: v for k, v in out.items() if k not in ("details",)} | {"details_frames": [d["frame"] for d in out.get("details", [])]})
    return {"PASS": 0, "WARN": 0}.get(out["status"], 3) if not args.strict else {"PASS": 0}.get(out["status"], 3)


@register
def _register(commands: Any, add_campaign_option: Any) -> None:
    parser = commands.add_parser("check", help="Value checks: band edges after the SCFs, NAC values after collect")
    sub = parser.add_subparsers(dest="check_command", required=True)
    edges = sub.add_parser("edges", help="Is the NAMD window an isolated, unchanged pair of states? (EIGENVAL/PROCAR)")
    add_campaign_option(edges)
    edges.add_argument("--degenerate-ev", type=float, default=KT_300K_EV, help="neighbour-band threshold (eV)")
    edges.add_argument("--drift", type=float, default=TVD_WARN, help="make-up drift threshold (0-1)")
    edges.add_argument("--detail", type=int, default=8, help="how many of the most changed frames to break down")
    edges.add_argument("--frames", help="extra frames to break down, e.g. 1,197,245")
    edges.add_argument("--strict", action="store_true", help="exit non-zero on WARN as well as FAIL")
    edges.set_defaults(func=_cmd)
    nacp = sub.add_parser("nac", help="NATXT/EIGTXT values: rows, antisymmetry, spikes, energies vs EIGENVAL")
    add_campaign_option(nacp)
    nacp.add_argument("--energy-tol", type=float, default=1e-3, help="EIGTXT vs EIGENVAL tolerance (eV)")
    nacp.add_argument("--strict", action="store_true", help="exit non-zero on WARN as well as FAIL")
    nacp.set_defaults(func=_cmd)
