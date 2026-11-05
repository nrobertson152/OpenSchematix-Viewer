# SPDX-License-Identifier: GPL-3.0-or-later
"""Open from RevisionWorx: pick a controlled OpenSchematix document and a revision (latest, released, or any
earlier one) and view a read-only copy of exactly that revision."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

SCHEMATIC_SUFFIXES = (".schematix", ".osch")


def schematic_documents(docs: list[dict]) -> list[dict]:
    return [d for d in docs if (d.get("path") or "").lower().endswith(SCHEMATIC_SUFFIXES)]


class OpenFromRevisionWorx(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Open from RevisionWorx")
        t = app.theme
        self.configure(bg=t.ui["surface"])
        f = ttk.Frame(self, style="Surface.TFrame", padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Open a controlled schematic", style="Title.TLabel").pack(anchor="w")
        ttk.Label(f, text="You get a read-only copy of the revision you choose; the controlled file is not touched.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        self.filter = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.filter, style="Search.TEntry")
        e.pack(fill="x")
        self.filter.trace_add("write", lambda *a: self.render())
        cols = ("project", "number", "title", "rev", "state", "released")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="browse", height=12)
        for c, title, w in zip(cols, ("Project", "Number", "Title", "Rev", "State", "Released"),
                               (150, 110, 220, 50, 120, 70)):
            self.tree.heading(c, text=title, anchor="w")
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=8)
        self.tree.bind("<Double-1>", lambda e: self.open("latest"))
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._revisions())
        row = ttk.Frame(f, style="Surface.TFrame")
        row.pack(fill="x")
        self.rev_var = tk.StringVar()
        ttk.Label(row, text="Revision", style="Surface.TLabel").pack(side="left")
        self.rev_box = ttk.Combobox(row, textvariable=self.rev_var, state="readonly", width=14)
        self.rev_box.pack(side="left", padx=6)
        ttk.Button(row, text="Open selected revision", command=lambda: self.open("chosen")).pack(side="left")
        ttk.Button(row, text="Cancel", command=self.destroy).pack(side="right")
        self.released_btn = ttk.Button(row, text="Open released", command=lambda: self.open("released"))
        self.released_btn.pack(side="right", padx=6)
        ttk.Button(row, text="Open latest", style="Accent.TButton", command=lambda: self.open("latest")).pack(side="right")
        self.message = ttk.Label(f, text="Loading…", style="Muted.TLabel")
        self.message.pack(anchor="w", pady=(8, 0))
        self.docs: list[dict] = []
        self.shown: list[dict] = []
        self.history: dict[str, list] = {}
        self.transient(app.root)
        e.focus_set()
        app._background(lambda: schematic_documents(app.rwx.documents()), self._loaded)

    def _loaded(self, docs, error):
        if not self.winfo_exists():
            return
        if error is not None:
            self.message.configure(text=str(error))
            return
        self.docs = docs or []
        self.render()

    def render(self):
        needle = self.filter.get().casefold()
        self.tree.delete(*self.tree.get_children())
        self.shown = [d for d in self.docs if not needle or needle in " ".join(
            (d["project"]["name"], d.get("number", ""), d.get("title", ""), d.get("path") or "")).casefold()]
        for i, d in enumerate(self.shown):
            latest, rel = d.get("latest") or {}, d.get("released") or {}
            self.tree.insert("", "end", iid=str(i), values=(d["project"]["name"], d.get("number", ""), d.get("title", ""),
                                                            latest.get("label", ""), latest.get("state_name", ""),
                                                            rel.get("label", "")))
        if self.shown:
            self.tree.selection_set("0")
        self.message.configure(text=f"{len(self.shown)} schematic document(s)" if self.docs else
                               "No OpenSchematix documents in this RevisionWorx workspace yet.")

    def selected(self) -> dict | None:
        sel = self.tree.selection()
        return self.shown[int(sel[0])] if sel else None

    def _revisions(self):
        d = self.selected()
        if not d:
            return
        self.released_btn.state(["!disabled"] if d.get("released") else ["disabled"])
        if d["id"] in self.history:
            self._fill_revs(d["id"])
            return
        self.app._background(lambda: self.app.rwx.document(d["id"]).get("history", []),
                             lambda hist, err: (self.history.__setitem__(d["id"], hist or []), self._fill_revs(d["id"]))
                             if self.winfo_exists() else None)

    def _fill_revs(self, doc_id):
        labels = [f"{r['label']} · {r['state_name']}" for r in reversed(self.history.get(doc_id, []))]
        self.rev_box.configure(values=labels)
        if labels:
            self.rev_box.current(0)

    def open(self, which: str):
        d = self.selected()
        if not d:
            return
        revision = None
        if which == "chosen":
            value = self.rev_var.get()
            if not value:
                messagebox.showinfo("Open from RevisionWorx", "Choose a revision first.", parent=self)
                return
            revision = value.split(" · ")[0]
        if self.app.open_revision(d, revision=revision, released=which == "released"):
            self.destroy()
