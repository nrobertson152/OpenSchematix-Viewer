# OpenSchematix Viewer — development workflow

Same rules as OpenSchematix (Director decision, 2026-11-04): Claude is the sole developer and may merge its own
work when the required CI passes on the exact head. Releases, release/version tags and licensing are the
Director's (`nrobertson152`) alone.

## Product rules

- GPL-3.0-or-later; fully offline: no network access, accounts, telemetry or ads.
- **Read-only:** nothing in the viewer may change or save a project file. Exports write new files only and refuse
  the open project's path.
- Runtime dependencies: the Python standard library (Tkinter) and OpenSchematix, pinned to an exact commit in
  `pyproject.toml`. Data comes from `openschematix.api`; the look from OpenSchematix's interface modules. Update
  the pin deliberately and run the full suite.
- RevisionWorx is optional and reached only through `osviewer/rwx_client.py` (a copy of RevisionWorx's
  `contrib/rwx_client.py`, contract `docs/INTEGRATION.md` there). Without it, its commands are hidden.
- Windows and Linux; Python 3.10–3.13.

## Work cycle

Work on a branch, open a focused PR, add regression tests that fail on the old code, record the exact SHA and
test counts on the PR, merge when CI passes on that SHA. Never weaken or skip tests to make CI green.

## Commands

```sh
python -m pip install -e ".[dev]"            # Linux also: sudo apt-get install -y xvfb python3-tk
xvfb-run -a python -m pytest -q -ra          # Windows: python -m pytest -q -ra
xvfb-run -a openschematix-viewer --self-test report.txt
```
