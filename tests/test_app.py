# SPDX-License-Identifier: GPL-3.0-or-later
"""The real viewer window (Tk, needs a display: xvfb-run on Linux). RevisionWorx is faked here; the real
integration is in test_revisionworx.py."""
import hashlib
import os
import shutil
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
pytestmark = pytest.mark.gui

from osviewer import app as appmod  # noqa: E402
from osviewer.settings import Settings  # noqa: E402

DEMO = Path(__file__).with_name("demo_project.schematix")


class FakeRwx:
    def __init__(self, status=None, fetch_to=None):
        self._status = status or {"controlled": False}
        self.fetch_to = fetch_to
        self.opened = []

    def available(self):
        return True

    def status(self, path):
        return self._status

    def open(self, document=None, file=None):
        self.opened.append(document or file)
        return {"launched": True}

    def fetch(self, ref, to_dir, revision=None, released=False):
        Path(to_dir).mkdir(parents=True, exist_ok=True)
        dest = Path(to_dir) / "demo (rev A).schematix"
        shutil.copy(DEMO, dest)
        return {"path": str(dest), "document_id": ref,
                "revision": {"label": revision or "A", "state": "released", "state_name": "Released"}}


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def demo(tmp_path):
    p = tmp_path / "demo.schematix"
    shutil.copy(DEMO, p)
    return p


def make(root, tmp_path, rwx=False, path=None):
    a = appmod.ViewerApp(root, path, settings=Settings(tmp_path / "cfg"), rwx=rwx)
    root.update()
    return a


def test_open_navigate_find_and_inspect(root, tmp_path, demo):
    a = make(root, tmp_path)
    assert a.open_path(str(demo))
    root.update()
    assert a.sheet_label.cget("text").startswith("1 / 3")
    a.next_sheet()
    a.next_sheet()
    a.next_sheet()                                          # stops at the last sheet
    assert a.sheet == 2
    a.prev_sheet()
    assert a.sheet == 1
    a.search_var.set("fuse")
    root.update()
    assert a.comp_list.get_children() == ("0",)
    a.comp_list.selection_set("0")
    root.update()
    a._component_picked()
    assert a.sheet == 0 and a.canvas.selected and a.insp_title.cget("text") == "F1"
    assert "recent" in a.settings.data and a.settings["recent"][0] == str(demo.resolve())


def test_click_selects_the_component_under_the_mouse(root, tmp_path, demo):
    a = make(root, tmp_path)
    a.open_path(str(demo))
    f1 = a.doc.search("fuse")[0]
    box = a.doc.component_bbox(0, f1.id)
    x, y = a.canvas.to_screen(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2))
    a._canvas_click(type("E", (), {"x": x, "y": y})())
    assert a.canvas.selected == {f1.id} and a.insp_title.cget("text") == "F1"
    a._canvas_click(type("E", (), {"x": 2, "y": 2})())
    assert a.canvas.selected == set() and a.insp_title.cget("text") == "Conveyor station 3"


def test_wire_list_highlights_the_net(root, tmp_path, demo):
    a = make(root, tmp_path)
    a.open_path(str(demo))
    i = next(i for i, n in enumerate(a._nets) if n["number"] == "1")
    a.wire_list.selection_set(str(i))
    root.update()
    a._wire_picked()
    assert a.insp_title.cget("text") == "Wire 1" and len(a.canvas.selected) >= 2


def test_exports_never_overwrite_the_project(root, tmp_path, demo, monkeypatch):
    a = make(root, tmp_path)
    a.open_path(str(demo))
    before = hashlib.sha256(demo.read_bytes()).hexdigest()
    errors = []
    monkeypatch.setattr(appmod.messagebox, "showerror", lambda *x, **k: errors.append(x))
    monkeypatch.setattr(appmod.filedialog, "asksaveasfilename", lambda **k: str(demo))
    a.export_pdf()
    a.export_svg()
    a.export_bom()
    assert len(errors) == 3 and hashlib.sha256(demo.read_bytes()).hexdigest() == before
    out = tmp_path / "out.pdf"
    monkeypatch.setattr(appmod.filedialog, "asksaveasfilename", lambda **k: str(out))
    a.export_pdf()
    assert out.read_bytes().startswith(b"%PDF")
    csv = tmp_path / "bom.csv"
    monkeypatch.setattr(appmod.filedialog, "asksaveasfilename", lambda **k: str(csv))
    a.export_bom()
    assert "FU-2A" in csv.read_text(encoding="utf-8")


def test_theme_switch_is_remembered(root, tmp_path, demo):
    a = make(root, tmp_path)
    a.open_path(str(demo))
    a.set_theme("blueprint")
    assert a.canvas.theme.name == "blueprint" and Settings(tmp_path / "cfg")["theme"] == "blueprint"
    a.cycle_theme()
    assert a.theme.name != "blueprint"


def test_damaged_file_shows_a_message(root, tmp_path, monkeypatch):
    bad = tmp_path / "bad.schematix"
    bad.write_bytes(b"not a project")
    errors = []
    monkeypatch.setattr(appmod.messagebox, "showerror", lambda *x, **k: errors.append(x))
    a = make(root, tmp_path)
    assert not a.open_path(str(bad)) and errors and a.doc is None


def test_file_changed_on_disk_is_reloaded(root, tmp_path, demo):
    a = make(root, tmp_path)
    a.open_path(str(demo))
    first = a.doc
    os.utime(demo, ns=(demo.stat().st_atime_ns, demo.stat().st_mtime_ns + 10_000_000_000))
    a._watch_file()
    assert a.doc is not first and a.doc.path == first.path


def test_revisionworx_status_chip(root, tmp_path, demo):
    status = {"controlled": True, "workspace": {}, "file": {"state": "unchanged", "matches_latest": True},
              "document": {"id": "doc_1", "number": "DWG-7", "title": "Conveyor",
                           "latest": {"label": "B", "state": "released", "state_name": "Released"}, "checkout": None}}
    rwx = FakeRwx(status)
    a = make(root, tmp_path, rwx=rwx)
    a.open_path(str(demo))
    for _ in range(50):
        root.update()
        if a.rwx_status:
            break
        root.after(20)
        a._poll()
    assert a.rwx_summary() == ("DWG-7 rev B · Released", "success")
    assert a.rwx_chip.winfo_manager() == "pack"
    a.show_in_rwx()
    assert rwx.opened == [str(demo.resolve())]
    status["file"]["state"] = "modified-externally"
    assert a.rwx_summary()[1] == "warning" and "differs" in a.rwx_summary()[0]


def test_open_revision_from_revisionworx_is_a_read_only_copy(root, tmp_path):
    rwx = FakeRwx()
    a = make(root, tmp_path, rwx=rwx)
    doc = {"id": "doc_9", "number": "DWG-9", "title": "Conveyor", "latest": {"label": "C"}}
    assert a.open_revision(doc, revision="A")
    assert a.fetched["revision"]["label"] == "A" and "DWG-9 rev A" in a.rwx_summary()[0]
    assert a.rwx_summary()[1] == "warning" and "latest is C" in a.rwx_summary()[0]
    assert str(Path(a.doc.path).parent).endswith("doc_9")
    assert a.settings["recent"] == []                       # copies are not added to Recent


def test_without_revisionworx_the_integration_is_hidden(root, tmp_path, demo):
    a = make(root, tmp_path, rwx=False)
    a.open_path(str(demo))
    assert a.rwx_summary() == ("", "muted") and not a.rwx_open_btn.winfo_ismapped()
    assert a.rwx_menu.entrycget(0, "state") == "disabled"


def test_about_and_shortcuts(root, tmp_path):
    from osviewer import VERSION
    a = make(root, tmp_path)
    about = a.show_about()
    texts = [w.cget("text") for w in about.winfo_children()[0].winfo_children() if isinstance(w, tk.ttk.Label)]
    assert any("Free and open-source" in t for t in texts)
    labels = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.ttk.Label):
                labels.append(c.cget("text"))
            walk(c)
    walk(about)
    assert f"Version {VERSION}" in labels and "OpenSchematix Viewer" in labels
    about.destroy()
    keys = a.show_shortcuts()
    keys.destroy()


def test_self_test_passes(root, tmp_path):
    from osviewer.selftest import run
    root.destroy()
    report = tmp_path / "r.txt"
    assert run(report) == 0, report.read_text()
    assert report.read_text().rstrip().endswith("self-test PASSED")
