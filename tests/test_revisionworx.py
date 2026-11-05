# SPDX-License-Identifier: GPL-3.0-or-later
"""End to end with the real RevisionWorx (installed by the [dev] extra): a schematic controlled in a real
workspace shows its revision in the viewer, and an earlier revision opens as a read-only copy."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("revisionworx.integration")
tk = pytest.importorskip("tkinter")
pytestmark = pytest.mark.gui

from osviewer import app as appmod  # noqa: E402
from osviewer.rwx_client import RevisionWorx  # noqa: E402
from osviewer.settings import Settings  # noqa: E402

DEMO = Path(__file__).with_name("demo_project.schematix")


def rwx_cli(env, *args):
    out = subprocess.run([sys.executable, "-m", "revisionworx", *args], capture_output=True, text=True, env=env,
                         timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    return out.stdout


@pytest.fixture
def controlled(tmp_path, monkeypatch):
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(tmp_path / "profile" / var))
    ws = tmp_path / "ws"
    monkeypatch.setenv("REVISIONWORX_WORKSPACE", str(ws))
    env = dict(os.environ)
    rwx_cli(env, "init", str(ws), "--name", "Viewer test")
    (ws / "Projects").mkdir()
    rwx_cli(env, "root", "add", "Projects", str(ws / "Projects"))
    rwx_cli(env, "project", "new", "--name", "Conveyor", "--number", "CS3")
    src = tmp_path / "conveyor.schematix"
    shutil.copy(DEMO, src)
    made = json.loads(rwx_cli(env, "link", "publish", str(src), "--project", "CS3", "--number", "DWG-100",
                              "--title", "Conveyor schematic", "-m", "Initial"))
    rev_a = made["document"]["latest"]["id"]
    for state in ("in_review", "approved", "released"):
        rwx_cli(env, "rev", "transition", rev_a, state)
    working = Path(made["document"]["path"])
    return env, working, made["document"]


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


def wait(root, app, attr):
    for _ in range(300):
        root.update()
        app._poll()
        if getattr(app, attr):
            return
        root.after(20)
    raise AssertionError(f"{attr} never arrived")


def test_status_of_a_controlled_schematic(root, tmp_path, controlled):
    env, working, doc = controlled
    rwx = RevisionWorx(executable=None)
    rwx.command = [sys.executable, "-m", "revisionworx"]
    assert rwx.available()
    a = appmod.ViewerApp(root, None, settings=Settings(tmp_path / "cfg"), rwx=rwx)
    assert a.open_path(str(working))
    wait(root, a, "rwx_status")
    assert a.rwx_status["controlled"] and a.rwx_summary() == ("DWG-100 rev A · Released", "success")


def test_open_any_revision_as_a_copy(root, tmp_path, controlled):
    env, working, doc = controlled
    rwx = RevisionWorx()
    rwx.command = [sys.executable, "-m", "revisionworx"]
    docs = [d for d in rwx.documents() if d["number"] == "DWG-100"]
    from osviewer.rwx_dialog import schematic_documents
    assert schematic_documents(docs) == docs
    a = appmod.ViewerApp(root, None, settings=Settings(tmp_path / "cfg"), rwx=rwx)
    assert a.open_revision(docs[0], released=True)
    assert a.fetched["revision"]["label"] == "A" and Path(a.doc.path) != working
    assert Path(a.doc.path).read_bytes() == working.read_bytes()
    assert a.doc.title == "Conveyor station 3"
