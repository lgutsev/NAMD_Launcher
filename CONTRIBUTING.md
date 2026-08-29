# Contributing

```bash
pip install -e ".[dev]"
python -m compileall -q src
python -m pytest -q            # on a locked-down Windows temp dir: add --basetemp=<writable>
ruff check src tests
```

Passing the tests means the Python contracts still hold; it does **not** mean a
stage has been validated against the real external engine. Every new
engine/version/cluster combination needs a small human-checked smoke run.

## House rules (shared with InterfaceForge)

- One JSON object to stdout per command; `ERROR: …` to stderr, exit 2.
- New stage = new module in `src/namd_launcher/`, a `STAGE` constant, `@register`
  for its subparser, and `<stage>_manifest.json` + `<stage>_audit.{json,tsv,md}`
  via `namd_launcher._stage`.
- Refuse to overwrite an existing output tree; `--execute` gates every cluster
  submission.
- Don't guess physics. Validation checks structure and consistency
  (column counts, band-window arithmetic); it never invents a band index,
  temperature, or `NBANDS`.
- Reuse `namd_launcher._compat` (InterfaceForge helpers when installed) rather
  than reimplementing INCAR/POTCAR/scheduler logic.

## External engines

NAMD Launcher redistributes **no** CA-NAC / VaspBandUnfolding / Hefei-NAMD
code. `third_party/` holds only `README.md` + `fetch.sh` (pinned commits).
Resolve installs through `namd_launcher._deps` (campaign key → env var →
`third_party/_src/` → importable); never copy engine source into the repo or a
campaign directory.
