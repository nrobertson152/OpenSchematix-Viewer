# SPDX-License-Identifier: GPL-3.0-or-later
"""``openschematix-viewer --self-test REPORT``: open the bundled demo project in the real window, step through
its sheets, find and select a component, export a PDF to a temporary folder, close, and write PASSED or FAILED.
Proves that an installed or packaged copy works (a windowed Windows executable has no console)."""
from __future__ import annotations

import shutil
import tempfile
import tkinter as tk
import traceback
from pathlib import Path

DEMO = Path(__file__).resolve().parent / "demo" / "demo_project.schematix"


def run(report: Path) -> int:
    from . import VERSION
    from .app import ViewerApp
    from .settings import Settings
    lines, ok = [f"version {VERSION}"], False
    tmp = Path(tempfile.mkdtemp(prefix="osviewer-selftest-"))
    try:
        root = tk.Tk()
        app = ViewerApp(root, None, settings=Settings(tmp / "cfg"), rwx=False)
        root.update()
        assert app.open_path(str(DEMO)), "the demo project did not open"
        sheets = app.doc.sheet_names()
        for i in range(len(sheets)):
            app.show_sheet(i)
            root.update()
        rows = app.doc.search("fuse")
        app.go_to_component(rows[0].sheet_index, rows[0].id)
        root.update()
        assert app.canvas.selected == {rows[0].id}
        from openschematix.export import export_project_pdf
        pdf = tmp / "out.pdf"
        export_project_pdf(app.doc.internal, str(pdf))
        assert pdf.read_bytes().startswith(b"%PDF"), "the PDF export is not a PDF"
        lines += [f"sheets: {len(sheets)}", f"components: {len(app.doc.components())}", f"pdf bytes: {pdf.stat().st_size}"]
        app.quit()
        ok = True
    except BaseException as exc:  # noqa: BLE001
        lines.append("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    lines.append("self-test " + ("PASSED" if ok else "FAILED"))
    Path(report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1
