"""Minimal, dependency-free VASP XDATCAR / POSCAR handling.

Only what the snapshot stage needs: read the ionic configurations from an
XDATCAR (or XDATCAR_FINAL), and write each one back as a VASP-5 Direct POSCAR.
ASE is used instead when it is installed and the file is unusual, but the
common case does not require it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Trajectory:
    comment: str
    scale: float
    lattice: list[list[float]]
    species: list[str]
    counts: list[int]
    frames: list[list[list[float]]]  # frame -> ion -> [x, y, z] (fractional)

    @property
    def n_ions(self) -> int:
        return sum(self.counts)

    def __len__(self) -> int:
        return len(self.frames)


def _floats(line: str) -> list[float]:
    return [float(tok) for tok in line.split()]


def read_xdatcar(path: str | Path) -> Trajectory:
    """Parse an XDATCAR / XDATCAR_FINAL.

    Tolerates the well-known glitch where VASP writes a blank line instead of
    the ``Direct configuration=`` marker between frames (the ``sed`` fix in the
    CA-NAC tutorial), and a lattice that is re-printed every frame.
    """

    text = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(text) < 8:
        raise ValueError(f"{path}: too short to be an XDATCAR")

    comment = text[0].strip()
    scale = float(text[1].split()[0])
    lattice = [_floats(text[2]), _floats(text[3]), _floats(text[4])]
    species = text[5].split()
    if not species or species[0][0].isdigit():
        raise ValueError(f"{path}: expected a VASP-5 species line at line 6, got {text[5]!r}")
    counts = [int(tok) for tok in text[6].split()]
    n_ions = sum(counts)

    frames: list[list[list[float]]] = []
    i = 7
    lines = text
    while i < len(lines):
        marker = lines[i].strip()
        i += 1
        if not marker:
            continue
        low = marker.lower()
        if low.startswith("direct configuration") or low in {"direct", "d"}:
            pass
        elif _looks_like_lattice_reprint(lines, i - 1, lattice):
            # A per-frame lattice re-print: skip its 5 header lines then expect
            # a Direct marker.
            i += 5
            if i < len(lines) and lines[i].strip().lower().startswith(("direct", "d")):
                i += 1
        else:
            # Treat a bare coordinate block (blank-line separated) as a frame:
            # step back one line so the loop below reads it.
            i -= 1
        coords: list[list[float]] = []
        for _ in range(n_ions):
            if i >= len(lines):
                break
            coords.append(_floats(lines[i])[:3])
            i += 1
        if len(coords) == n_ions:
            frames.append(coords)

    if not frames:
        raise ValueError(f"{path}: no ionic configurations found")
    return Trajectory(comment, scale, lattice, species, counts, frames)


def _looks_like_lattice_reprint(lines: list[str], idx: int, lattice: list[list[float]]) -> bool:
    try:
        return abs(float(lines[idx].split()[0]) - 1.0) < 1e-6 and len(lines[idx + 1].split()) == 3
    except (ValueError, IndexError):
        return False


def write_poscar(traj: Trajectory, frame_index: int, out_path: str | Path, *, comment: str | None = None) -> Path:
    """Write one frame as a VASP-5 Direct POSCAR."""

    frame = traj.frames[frame_index]
    lines = [
        comment or traj.comment or "snapshot",
        f"{traj.scale:.14f}".rstrip("0").rstrip(".") if traj.scale != 1.0 else "1.0",
    ]
    for row in traj.lattice:
        lines.append("  " + "  ".join(f"{value:.16f}" for value in row))
    lines.append("  " + "  ".join(traj.species))
    lines.append("  " + "  ".join(str(count) for count in traj.counts))
    lines.append("Direct")
    for xyz in frame:
        lines.append("  " + "  ".join(f"{value:.16f}" for value in xyz))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
