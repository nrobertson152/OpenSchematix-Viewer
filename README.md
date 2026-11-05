# OpenSchematix Viewer

**A free, read-only viewer for [OpenSchematix](https://github.com/nrobertson152/OpenSchematix) projects, for
the shop floor, reviewers and anyone without OpenSchematix installed.** Part of the RevisionWorx family: with
[RevisionWorx](https://github.com/nrobertson152/RevisionWorx) installed it shows each drawing's revision status
and opens any controlled revision.

Windows and Linux. Offline: no accounts, no telemetry, no ads, no feature limits. GPL-3.0-or-later.

## Features

- **Exactly what OpenSchematix draws.** The viewer uses OpenSchematix's own renderer, themes and icons: every
  symbol, wire, junction, wire number, cross-reference, fill and title block looks the same.
- **Never changes a file.** Nothing in the viewer can edit or save a project. Exports go to new files only and
  refuse to overwrite the open project.
- **Find anything.** Search components by designator, description, part number, manufacturer or rating, then
  jump straight to them. Click any component on the sheet to see its properties and terminals.
- **Every sheet, BOM and wire.** Sheet list and Page Up/Down; the bill of materials; every wire with its number
  and connected terminals (select one to highlight it on the sheet).
- **Title block and project details** at a glance.
- **Export** the project as PDF, a sheet as SVG, the BOM as CSV.
- **Follows the file.** When the project is saved in OpenSchematix, or a new revision is checked in to
  RevisionWorx, the viewer reloads it.
- **Same colour themes as OpenSchematix:** Modern Light, Modern Dark, Graphite, Neutral Gray, Blueprint and High
  Contrast.

### With RevisionWorx

- The toolbar shows the open drawing's document number, revision and state (for example
  "DWG-100 rev B · Released"), and warns when the file differs from the latest revision or is checked out.
- **Open from RevisionWorx** (Ctrl+Shift+O): choose a controlled schematic and open its latest, released or any
  earlier revision as a read-only copy. The controlled file is never touched.
- **Show in RevisionWorx** opens the document in the RevisionWorx window.

RevisionWorx is optional. Without it these commands are hidden and everything else works.

## Install

**Standalone:** download `OpenSchematix-Viewer-<version>-windows-x64.zip` or `…-linux-x86_64.tar.gz` from the
releases, check it against its `.sha256` file, unpack, and run `openschematix-viewer`.

**With Python 3.10+ (and Tk):**

```bash
pip install "git+https://github.com/nrobertson152/OpenSchematix-Viewer"
openschematix-viewer [project.schematix]
openschematix-viewer --self-test report.txt     # proves an installation works
```

## Keyboard

Ctrl+O open · Ctrl+Shift+O open from RevisionWorx · Ctrl+F find · F or Home fit · + / − zoom · Page Up/Down
sheets · Ctrl+E export PDF · F5 reload · Ctrl+W close · F1 all shortcuts. Middle-drag pans; the wheel zooms.

## Development

```bash
python -m pip install -e ".[dev]"     # Linux also: sudo apt-get install -y xvfb python3-tk
xvfb-run -a python -m pytest -q -ra   # Windows: python -m pytest -q -ra
```

The viewer depends on OpenSchematix, pinned to an exact commit in `pyproject.toml`: besides the public scripting
API it uses OpenSchematix's interface modules (themes, widgets, canvas), which are not a public API. Update the
pin deliberately and run the tests. The `[dev]` extra installs RevisionWorx for the end-to-end integration tests.

## License

GPL-3.0-or-later. Copyright © 2026 Nate Robertson. The application icon is OpenSchematix's.
