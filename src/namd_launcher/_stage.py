"""Shared helpers for pipeline stages: manifests, audits, and safe writes.

Every stage writes ``<stage>_manifest.json`` plus ``<stage>_audit.{json,tsv,md}``
into its output directory, matching the shapes InterfaceForge's ``step2_*``
files use, so ``inamd audit`` / ``inamd status`` (and a human) can read a
campaign the same way regardless of which tool produced a given tree.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .errors import SafetyError

STATUS_ORDER = {"FAIL": 3, "WARN": 2, "PASS": 1, "PENDING": 0}


def refuse_existing(path: Path, *, what: str = "output") -> None:
    """Mirror InterfaceForge: never silently overwrite an existing output tree."""

    if path.exists():
        raise SafetyError(f"Refusing to overwrite existing {what}: {path}. Move it aside or pick another location.")


def rollup_status(statuses: Sequence[str]) -> str:
    if not statuses:
        return "PENDING"
    return max(statuses, key=lambda s: STATUS_ORDER.get(s, 0))


def write_manifest(root: Path, stage: str, payload: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{stage}_manifest.json"
    body = {"format": f"namdforge-{stage}-manifest", "schema_version": 1, **payload}
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_audit(
    root: Path,
    stage: str,
    audit: dict[str, Any],
    *,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Write ``<stage>_audit.{json,tsv,md}``. ``rows`` drives the TSV/MD table."""

    root.mkdir(parents=True, exist_ok=True)
    body = {"format": f"namdforge-{stage}-audit", "schema_version": 1, **audit}
    json_path = root / f"{stage}_audit.json"
    json_path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    table_rows = rows if rows is not None else audit.get("runs", [])
    tsv_path = root / f"{stage}_audit.tsv"
    md_path = root / f"{stage}_audit.md"
    if table_rows:
        fields = list(table_rows[0].keys())
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in table_rows:
            writer.writerow({key: row.get(key, "") for key in fields})
        tsv_path.write_text(buffer.getvalue(), encoding="utf-8")

        md = [f"# {stage} audit", "", f"**status:** {audit.get('status', 'PENDING')}", ""]
        md.append("| " + " | ".join(fields) + " |")
        md.append("| " + " | ".join("---" for _ in fields) + " |")
        for row in table_rows:
            md.append("| " + " | ".join(str(row.get(key, "")) for key in fields) + " |")
        md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    else:
        tsv_path.write_text("status\n" + f"{audit.get('status', 'PENDING')}\n", encoding="utf-8")
        md_path.write_text(
            f"# {stage} audit\n\n**status:** {audit.get('status', 'PENDING')}\n\n"
            f"{audit.get('summary', '')}\n",
            encoding="utf-8",
        )
    return {"json": str(json_path), "tsv": str(tsv_path), "md": str(md_path)}


def read_manifest(root: Path, stage: str) -> dict[str, Any] | None:
    path = Path(root) / f"{stage}_manifest.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def read_audit(root: Path, stage: str) -> dict[str, Any] | None:
    path = Path(root) / f"{stage}_audit.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
