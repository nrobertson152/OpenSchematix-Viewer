# Changelog

## 1.0.0 (unreleased)

First release.

- Read-only viewer for `.schematix` projects and legacy `.osch` drawings, drawn by OpenSchematix's own renderer
  with its six colour themes.
- Sheets, components (search, jump to, click to inspect), BOM, wires (select to highlight), title block.
- Export project PDF, sheet SVG and BOM CSV; exports never overwrite the open project.
- Reloads when the file changes on disk.
- RevisionWorx integration: revision status in the toolbar, Open from RevisionWorx (latest, released or any
  revision, as a read-only copy), Show in RevisionWorx. Hidden when RevisionWorx is not installed.
- `--self-test` for installed and packaged copies; standalone Windows and Linux builds.
