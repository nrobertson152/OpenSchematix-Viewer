# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSchematix Viewer window (Tk).

Built from OpenSchematix's own interface pieces (themes, toolbar icons, drawing canvas, renderer), so it looks
and draws exactly like OpenSchematix. Strictly read-only: no command here can change or save a project file.
RevisionWorx integration (revision status, open a controlled revision, show in RevisionWorx) runs in the
background and is hidden when RevisionWorx is not installed."""
from __future__ import annotations

import os
import platform
import queue
import sys
import tempfile
import threading
import tkinter as tk
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from openschematix.gui import theme as th
from openschematix.gui.canvas_view import PreviewView, draw_items
from openschematix.gui.widgets import IconButton, ToastHost, Tooltip, ToolbarSeparator, make_menu, set_current_theme
from openschematix.render import scene

from . import APP_NAME, COPYRIGHT, DONATE_URL, FILE_TYPES, LICENSE_NAME, LICENSE_URL, REPO_URL, VERSION
from .document import ViewerDocument, ViewerError
from .settings import Settings

SHORTCUTS = (("Ctrl+O", "Open a project"), ("Ctrl+Shift+O", "Open a controlled revision from RevisionWorx"),
             ("Ctrl+E", "Export the project as PDF"), ("Ctrl+F", "Find a component"),
             ("F / Home", "Fit the sheet"), ("+ / -", "Zoom in / out"), ("Page Down / Page Up", "Next / previous sheet"),
             ("Mouse wheel", "Zoom (Shift: pan sideways, Ctrl: pan up and down)"), ("Middle drag", "Pan"),
             ("Click", "Select a component and show its properties"), ("F5", "Reload the file"),
             ("Ctrl+W", "Close the file"), ("F1", "This list"))


def resource_path(name: str) -> str:
    """OpenSchematix's resources (the family icon), from the installed package or a frozen build."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = os.path.join(base, "openschematix", "resources", name)
        if os.path.exists(p):
            return p
    import openschematix
    return os.path.join(os.path.dirname(openschematix.__file__), "resources", name)


class ViewerCanvas(PreviewView):
    """PreviewView with a highlighted selection (components or wires, by item id)."""

    def __init__(self, master, theme, **kw):
        super().__init__(master, theme, **kw)
        self.selected: set = set()
        self.project = None

    def _redraw_now(self):
        self._redraw_pending = False
        self.delete("all")
        c = self.theme
        self.configure(bg=c["desk"])
        if self.doc is None:
            return
        W, H = self.doc.sheet.size_units()
        self.draw_paper(c, W, H)
        draw_items(self, scene(self.doc, screen=False, project=self.project), self.to_screen, self.zoom, c,
                   self.font_family, selected=self.selected)
        self.view_changed()


class ViewerApp:
    def __init__(self, root: tk.Tk, path: str | None = None, settings: Settings | None = None, rwx=None):
        self.root = root
        self.settings = settings or Settings()
        self.theme = th.Theme(self.settings["theme"])
        set_current_theme(self.theme)
        th.apply(root, self.theme)
        self.doc: ViewerDocument | None = None
        self.sheet = 0
        self.rwx = rwx
        self.rwx_status: dict | None = None
        self.fetched: dict | None = None          # set when the open file is a revision copied from RevisionWorx
        self._jobs: "queue.Queue" = queue.Queue()
        self._mtime = None
        self._load_icon()
        root.title(APP_NAME)
        root.minsize(900, 560)
        root.geometry(self.settings["geometry"] or "1360x860")
        self._build()
        self._bind_keys()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.after(100, self._poll)
        root.after(2000, self._watch_file)
        if self.rwx is None:
            self._background(self._probe_rwx, self._rwx_ready)
        else:
            root.after(0, lambda: self._rwx_ready(self.rwx or None, None))
        if path:
            root.after(50, lambda: self.open_path(path))
        else:
            self.show_welcome()

    # ================================================================ construction
    def _load_icon(self):
        try:
            self.icon_image = tk.PhotoImage(file=resource_path("openschematix-64.png"))
            self.root.iconphoto(True, self.icon_image)
        except tk.TclError:
            self.icon_image = None

    def _build(self):
        self._build_menu()
        u = self.theme.ui
        self.toolbar = ttk.Frame(self.root, style="Toolbar.TFrame", padding=(8, 4))
        self.toolbar.pack(fill="x")
        tb = self.toolbar

        def btn(icon, cmd, tip):
            b = IconButton(tb, icon, cmd, tip)
            b.pack(side="left", padx=1)
            return b
        btn("open", self.open_dialog, "Open a project (Ctrl+O)")
        self.rwx_open_btn = btn("revision", self.open_from_rwx, "Open a controlled revision from RevisionWorx "
                                                                "(Ctrl+Shift+O)")
        btn("pdf", self.export_pdf, "Export the project as PDF (Ctrl+E)")
        ToolbarSeparator(tb).pack(side="left", padx=7, pady=3)
        btn("zoom_in", lambda: self.canvas.zoom_by(1.25), "Zoom in (+)")
        btn("zoom_out", lambda: self.canvas.zoom_by(0.8), "Zoom out (-)")
        btn("zoom_fit", self.fit, "Fit the sheet (F)")
        ToolbarSeparator(tb).pack(side="left", padx=7, pady=3)
        btn("chevron_left", self.prev_sheet, "Previous sheet (Page Up)")
        self.sheet_label = ttk.Label(tb, text="", style="Toolbar.TLabel", width=24, anchor="center")
        self.sheet_label.pack(side="left", padx=4)
        btn("chevron_right", self.next_sheet, "Next sheet (Page Down)")
        ToolbarSeparator(tb).pack(side="left", padx=7, pady=3)
        btn("search", self.focus_search, "Find a component (Ctrl+F)")
        btn("theme", self.cycle_theme, "Next colour theme")
        btn("help", self.show_shortcuts, "Keyboard shortcuts (F1)")
        self.rwx_show_btn = IconButton(tb, "project", self.show_in_rwx, "Show this document in RevisionWorx")
        self.rwx_chip = tk.Label(tb, text="", padx=10, pady=3, bd=0, font=self.theme.fonts["small"])
        Tooltip(self.rwx_chip, "Revision status from RevisionWorx")
        ttk.Separator(self.root).pack(fill="x")

        self.status_bar = ttk.Frame(self.root, style="Status.TFrame", padding=(10, 3))
        self.status_bar.pack(fill="x", side="bottom")
        self.status_left = ttk.Label(self.status_bar, text="", style="Status.TLabel")
        self.status_left.pack(side="left")
        self.status_right = ttk.Label(self.status_bar, text="", style="Status.TLabel")
        self.status_right.pack(side="right")
        ttk.Separator(self.root).pack(fill="x", side="bottom")

        self.pane = ttk.PanedWindow(self.root, orient="horizontal")
        self.pane.pack(fill="both", expand=True)
        self.left = ttk.Notebook(self.pane)
        self.pane.add(self.left, weight=0)
        self.center = ttk.Frame(self.pane, style="Surface.TFrame")
        self.pane.add(self.center, weight=1)
        self.right = ttk.Frame(self.pane, style="Panel.TFrame", padding=12)
        self.pane.add(self.right, weight=0)

        # left: sheets, components, BOM, wires
        self.sheets_list = self._tree(self.left, ("name",), ("Sheet",), (200,))
        self.sheets_list.bind("<<TreeviewSelect>>", lambda e: self._sheet_picked())
        self.left.add(self.sheets_list.master, text="Sheets")
        comp_tab = ttk.Frame(self.left, style="Surface.TFrame", padding=(0, 6, 0, 0))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(comp_tab, textvariable=self.search_var, style="Search.TEntry")
        self.search_entry.pack(fill="x", padx=6, pady=(0, 6))
        Tooltip(self.search_entry, "Designator, description, part number, manufacturer…")
        self.search_var.trace_add("write", lambda *a: self._fill_components())
        self.comp_list = self._tree(comp_tab, ("des", "desc", "sheet"), ("Ref", "Description", "Sheet"),
                                    (60, 170, 90), pack=True)
        self.comp_list.bind("<<TreeviewSelect>>", lambda e: self._component_picked())
        self.left.add(comp_tab, text="Components")
        self.bom_list = self._tree(self.left, ("qty", "des", "desc", "pn"), ("Qty", "Ref", "Description", "Part no."),
                                   (40, 80, 150, 90))
        self.left.add(self.bom_list.master, text="BOM")
        self.wire_list = self._tree(self.left, ("num", "conn"), ("Wire", "Connects"), (60, 260))
        self.wire_list.bind("<<TreeviewSelect>>", lambda e: self._wire_picked())
        self.left.add(self.wire_list.master, text="Wires")

        # center: canvas, or the welcome page
        self.canvas = ViewerCanvas(self.center, self.theme)
        self.canvas.font_family = self.theme.fonts.get("family", "Helvetica")
        self.canvas.view_changed = self._view_changed
        self.canvas.bind("<ButtonRelease-1>", self._canvas_click)
        self.canvas.bind("<Double-Button-1>", lambda e: self.fit())
        self.welcome = ttk.Frame(self.center, style="Surface.TFrame", padding=40)
        self.toasts = ToastHost(self.center)

        # right: inspector
        self.insp_title = ttk.Label(self.right, text="", style="Title.TLabel", wraplength=230, justify="left")
        self.insp_title.pack(anchor="w")
        self.insp_sub = ttk.Label(self.right, text="", style="Muted.TLabel", wraplength=230, justify="left")
        self.insp_sub.pack(anchor="w", pady=(0, 10))
        self.insp_body = ttk.Frame(self.right, style="Panel.TFrame")
        self.insp_body.pack(fill="both", expand=True)
        self.root.update_idletasks()
        try:
            self.pane.sashpos(0, 300)
            self.pane.sashpos(1, max(600, self.root.winfo_width() - 280))
        except tk.TclError:
            pass

    def _tree(self, parent, cols, titles, widths, pack=False):
        frame = ttk.Frame(parent, style="Surface.TFrame") if not pack else parent
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        for c, t, w in zip(cols, titles, widths):
            tree.heading(c, text=t, anchor="w")
            tree.column(c, width=w, anchor="w", stretch=c in ("desc", "conn", "name"))
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        return tree

    def _build_menu(self):
        mb = make_menu(self.root)
        self.root.configure(menu=mb)
        self.menubar = mb
        f = make_menu(mb)
        f.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_dialog)
        f.add_command(label="Open from RevisionWorx…", accelerator="Ctrl+Shift+O", command=self.open_from_rwx)
        self.recent_menu = make_menu(f)
        f.add_cascade(label="Recent", menu=self.recent_menu)
        f.add_separator()
        f.add_command(label="Export PDF…", accelerator="Ctrl+E", command=self.export_pdf)
        f.add_command(label="Export sheet as SVG…", command=self.export_svg)
        f.add_command(label="Export BOM as CSV…", command=self.export_bom)
        f.add_separator()
        f.add_command(label="Reload", accelerator="F5", command=self.reload)
        f.add_command(label="Close", accelerator="Ctrl+W", command=self.close_file)
        f.add_command(label="Quit", accelerator="Ctrl+Q", command=self.quit)
        mb.add_cascade(label="File", menu=f)
        v = make_menu(mb)
        v.add_command(label="Fit sheet", accelerator="F", command=self.fit)
        v.add_command(label="Zoom in", accelerator="+", command=lambda: self.canvas.zoom_by(1.25))
        v.add_command(label="Zoom out", accelerator="-", command=lambda: self.canvas.zoom_by(0.8))
        v.add_separator()
        v.add_command(label="Next sheet", accelerator="Page Down", command=self.next_sheet)
        v.add_command(label="Previous sheet", accelerator="Page Up", command=self.prev_sheet)
        v.add_separator()
        self.theme_var = tk.StringVar(value=self.theme.name)
        tm = make_menu(v)
        for key, spec in th.THEMES.items():
            tm.add_radiobutton(label=spec["label"], value=key, variable=self.theme_var,
                               command=lambda k=key: self.set_theme(k))
        v.add_cascade(label="Colour theme", menu=tm)
        mb.add_cascade(label="View", menu=v)
        r = make_menu(mb)
        r.add_command(label="Revision status", command=self.show_rwx_status)
        r.add_command(label="Show in RevisionWorx", command=self.show_in_rwx)
        r.add_command(label="Open from RevisionWorx…", command=self.open_from_rwx)
        mb.add_cascade(label="RevisionWorx", menu=r)
        self.rwx_menu = r
        h = make_menu(mb)
        h.add_command(label="Keyboard shortcuts", accelerator="F1", command=self.show_shortcuts)
        h.add_command(label="Project page", command=lambda: webbrowser.open(REPO_URL))
        h.add_separator()
        h.add_command(label=f"About {APP_NAME}", command=self.show_about)
        mb.add_cascade(label="Help", menu=h)
        self._fill_recent()

    def _bind_keys(self):
        r = self.root
        for seq, fn in (("<Control-o>", self.open_dialog), ("<Control-O>", self.open_from_rwx),
                        ("<Control-Shift-o>", self.open_from_rwx), ("<Control-e>", self.export_pdf),
                        ("<Control-f>", self.focus_search), ("<Control-w>", self.close_file),
                        ("<Control-q>", self.quit), ("<F5>", self.reload), ("<F1>", self.show_shortcuts),
                        ("<Next>", self.next_sheet), ("<Prior>", self.prev_sheet), ("<Home>", self.fit)):
            r.bind_all(seq, lambda e, f=fn: (f(), "break")[1])
        for seq, fn in (("f", self.fit), ("plus", lambda: self.canvas.zoom_by(1.25)), ("equal",
                        lambda: self.canvas.zoom_by(1.25)), ("minus", lambda: self.canvas.zoom_by(0.8)),
                        ("KP_Add", lambda: self.canvas.zoom_by(1.25)), ("KP_Subtract", lambda: self.canvas.zoom_by(0.8))):
            r.bind_all(f"<Key-{seq}>", lambda e, f=fn: None if isinstance(e.widget, (tk.Entry, ttk.Entry)) else f())

    # ================================================================ files
    def open_dialog(self):
        start = os.path.dirname(self.doc.path) if self.doc else str(Path.home())
        path = filedialog.askopenfilename(parent=self.root, title="Open", filetypes=FILE_TYPES, initialdir=start)
        if path:
            self.open_path(path)

    def open_path(self, path: str, fetched: dict | None = None) -> bool:
        try:
            doc = ViewerDocument(path)
        except ViewerError as exc:
            messagebox.showerror(APP_NAME, f"Could not open {path}.\n\n{exc}", parent=self.root)
            return False
        except Exception as exc:  # noqa: BLE001 - a damaged file must give a message, never a crash
            messagebox.showerror(APP_NAME, f"Could not open {path}.\n\n{type(exc).__name__}: {exc}",
                                 parent=self.root)
            return False
        self.doc, self.sheet, self.fetched = doc, 0, fetched
        try:
            self._mtime = os.stat(doc.path).st_mtime_ns
        except OSError:
            self._mtime = None
        if not fetched:
            self.settings.remember(doc.path)
            self._fill_recent()
        self.welcome.pack_forget()
        self.canvas.pack(fill="both", expand=True)
        self.root.update_idletasks()          # the canvas needs its real size before the sheet is fitted
        self.canvas.project = doc.internal
        self.canvas.selected = set()
        self._fill_lists()
        self.show_sheet(0)
        self.show_inspector(None)
        self.root.title(f"{doc.name} — {APP_NAME}")
        if doc.warnings:
            self.toasts.show("\n".join(doc.warnings), "warning", 8000)
        self.refresh_rwx()
        return True

    def reload(self):
        if self.doc:
            sheet = self.sheet
            fetched = self.fetched
            if self.open_path(self.doc.path, fetched=fetched):
                self.show_sheet(min(sheet, len(self.doc.sheet_names()) - 1))
                self.toasts.show("Reloaded.", "info", 2000)

    def close_file(self):
        self.doc = None
        self.fetched = None
        self.canvas.doc = None
        self.canvas.pack_forget()
        for tree in (self.sheets_list, self.comp_list, self.bom_list, self.wire_list):
            tree.delete(*tree.get_children())
        self.show_inspector(None)
        self.root.title(APP_NAME)
        self.rwx_status = None
        self._render_rwx()
        self.show_welcome()

    def _watch_file(self):
        """A project changed on disk (saved in OpenSchematix, or a new revision checked in) is reloaded."""
        try:
            if self.doc is not None and self._mtime is not None:
                now = os.stat(self.doc.path).st_mtime_ns
                if now != self._mtime:
                    self._mtime = now
                    self.reload()
        except OSError:
            pass
        self.root.after(2000, self._watch_file)

    def _fill_recent(self):
        self.recent_menu.delete(0, "end")
        recent = [p for p in self.settings["recent"] if isinstance(p, str)]
        for p in recent:
            self.recent_menu.add_command(label=p, command=lambda q=p: self.open_path(q))
        if not recent:
            self.recent_menu.add_command(label="(none)", state="disabled")

    # ================================================================ welcome
    def show_welcome(self):
        for w in self.welcome.winfo_children():
            w.destroy()
        self.canvas.pack_forget()
        self.welcome.pack(fill="both", expand=True)
        ttk.Label(self.welcome, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.welcome, text="View OpenSchematix projects: every sheet, component, wire and part, without "
                                     "changing the file.", style="Muted.TLabel", wraplength=560,
                  justify="left").pack(anchor="w", pady=(4, 18))
        row = ttk.Frame(self.welcome, style="Surface.TFrame")
        row.pack(anchor="w")
        ttk.Button(row, text="Open a project…", style="Accent.TButton", command=self.open_dialog).pack(side="left")
        self.welcome_rwx_btn = ttk.Button(row, text="Open from RevisionWorx…", command=self.open_from_rwx)
        self.welcome_rwx_btn.pack(side="left", padx=8)
        recent = [p for p in self.settings["recent"] if isinstance(p, str)]
        if recent:
            ttk.Label(self.welcome, text="Recent", style="Heading.TLabel").pack(anchor="w", pady=(24, 4))
            for p in recent[:8]:
                b = ttk.Button(self.welcome, text=p, style="Link.TButton", command=lambda q=p: self.open_path(q))
                b.pack(anchor="w")
        self.sheet_label.configure(text="")
        self.status_left.configure(text="No file open")
        self.status_right.configure(text="")

    # ================================================================ lists
    def _fill_lists(self):
        d = self.doc
        self.sheets_list.delete(*self.sheets_list.get_children())
        for i, name in enumerate(d.sheet_names()):
            self.sheets_list.insert("", "end", iid=str(i), values=(f"{i + 1}. {name}",))
        self._fill_components()
        self.bom_list.delete(*self.bom_list.get_children())
        for b in d.bom():
            self.bom_list.insert("", "end", values=(b.quantity, b.designator_text, b.description or b.symbol,
                                                    b.part_number))
        self.wire_list.delete(*self.wire_list.get_children())
        self._nets = d.nets()
        for i, n in enumerate(self._nets):
            self.wire_list.insert("", "end", iid=str(i), values=(n["number"] or "–", "  ".join(n["terminals"])))

    def _fill_components(self):
        if self.doc is None:
            return
        self.comp_list.delete(*self.comp_list.get_children())
        self._comp_rows = self.doc.search(self.search_var.get())
        for i, r in enumerate(self._comp_rows):
            self.comp_list.insert("", "end", iid=str(i), values=(r.designator or "–", r.description or r.symbol,
                                                                 r.sheet))

    def _sheet_picked(self):
        sel = self.sheets_list.selection()
        if sel and int(sel[0]) != self.sheet:
            self.show_sheet(int(sel[0]))

    def _component_picked(self):
        sel = self.comp_list.selection()
        if not sel:
            return
        r = self._comp_rows[int(sel[0])]
        self.go_to_component(r.sheet_index, r.id)

    def _wire_picked(self):
        sel = self.wire_list.selection()
        if not sel or self.doc is None:
            return
        net = self._nets[int(sel[0])]
        uids = [s.uid for s in self.doc.api.sheets]
        if net["sheet_uids"]:
            first = uids.index(net["sheet_uids"][0]) if net["sheet_uids"][0] in uids else self.sheet
            if first != self.sheet:
                self.show_sheet(first)
        # highlight the net's wires and its components on this sheet
        this_uid = uids[self.sheet]
        ids = {wid for suid, wid in self._net_wires(net) if suid == this_uid}
        ids |= {t.component_id for t in net["refs"] if t.sheet_uid == this_uid}
        self.canvas.selected = ids
        self.canvas.redraw()
        self.show_net(net)

    def _net_wires(self, net):
        for n in self.doc.api.nets():
            if n.number == net["number"] and [f"{t.designator or '?'}:{t.terminal}" for t in n.terminals] == net["terminals"]:
                return n.wires
        return ()

    # ================================================================ sheets and view
    def show_sheet(self, index: int):
        if self.doc is None:
            return
        names = self.doc.sheet_names()
        index = max(0, min(len(names) - 1, index))
        self.sheet = index
        had_selection = bool(self.canvas.selected)
        self.canvas.selected = set()
        self.canvas.show(self.doc.sheet_doc(index), project=self.doc.internal)
        if had_selection:
            self.show_inspector(None)
        self.sheet_label.configure(text=f"{index + 1} / {len(names)}  {names[index]}")
        if self.sheets_list.selection() != (str(index),):
            self.sheets_list.selection_set(str(index))
        self._update_status()

    def next_sheet(self):
        if self.doc:
            self.show_sheet(self.sheet + 1)

    def prev_sheet(self):
        if self.doc:
            self.show_sheet(self.sheet - 1)

    def fit(self):
        if self.doc:
            self.canvas.fit()

    def _view_changed(self):
        self._update_status()

    def _update_status(self):
        if self.doc is None:
            return
        src = f"Revision {self.fetched['revision']['label']} copy · " if self.fetched else ""
        self.status_left.configure(text=f"{src}{self.doc.path}")
        self.status_right.configure(text=f"Sheet {self.sheet + 1} of {len(self.doc.sheet_names())} · "
                                         f"{int(round(self.canvas.zoom * 100))}% · read-only")

    def go_to_component(self, sheet_index: int, cid: int):
        if sheet_index != self.sheet:
            self.show_sheet(sheet_index)
        box = self.doc.component_bbox(sheet_index, cid)
        self.canvas.selected = {cid}
        if box:
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            self.canvas.center_on((cx, cy), zoom=max(self.canvas.zoom, 1.2))
        else:
            self.canvas.redraw()
        self.show_inspector(self.doc.component(sheet_index, cid))

    def _canvas_click(self, e):
        if self.doc is None or self.canvas.pan_from:
            return
        cid = self.doc.component_at(self.sheet, self.canvas.to_world(e.x, e.y))
        self.canvas.selected = {cid} if cid is not None else set()
        self.canvas.redraw()
        self.show_inspector(self.doc.component(self.sheet, cid) if cid is not None else None)

    def focus_search(self):
        self.left.select(1)
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    # ================================================================ inspector
    def _clear_inspector(self):
        for w in self.insp_body.winfo_children():
            w.destroy()

    def _field(self, label, value):
        if not value:
            return
        ttk.Label(self.insp_body, text=label, style="Muted.TLabel").pack(anchor="w")
        ttk.Label(self.insp_body, text=value, style="Panel.TLabel", wraplength=230, justify="left").pack(
            anchor="w", pady=(0, 6))

    def show_inspector(self, row):
        self._clear_inspector()
        if self.doc is None:
            self.insp_title.configure(text="")
            self.insp_sub.configure(text="")
            return
        if row is None:
            self.insp_title.configure(text=self.doc.title)
            self.insp_sub.configure(text=f"{len(self.doc.sheet_names())} sheet(s) · {len(self.doc.components())} "
                                         "component(s). Click a component for its details.")
            for label, value in self.doc.meta():
                self._field(label, value)
            return
        self.insp_title.configure(text=row.designator or row.symbol)
        self.insp_sub.configure(text=row.symbol)
        self._field("Description", row.description)
        self._field("Part number", row.part_number)
        self._field("Manufacturer", row.manufacturer)
        self._field("Rating", row.rating)
        self._field("Label", row.label)
        self._field("Terminals", ", ".join(row.terminals))
        for k, v in row.properties:
            if k not in ("description", "part_number", "manufacturer", "rating"):
                self._field(k.replace("_", " ").capitalize(), v)
        self._field("Sheet", f"{row.sheet_index + 1}. {row.sheet}")

    def show_net(self, net):
        self._clear_inspector()
        self.insp_title.configure(text=f"Wire {net['number']}" if net["number"] else "Unnumbered connection")
        self.insp_sub.configure(text="Connected terminals")
        for t in net["terminals"]:
            ttk.Label(self.insp_body, text=t, style="Panel.TLabel").pack(anchor="w")
        self._field("Sheets", ", ".join(net["sheets"]))

    # ================================================================ export (never writes the project)
    def _ask_save(self, title, ext, types, suggested):
        return filedialog.asksaveasfilename(parent=self.root, title=title, defaultextension=ext, filetypes=types,
                                            initialfile=suggested)

    def export_pdf(self):
        if self.doc is None:
            return
        path = self._ask_save("Export PDF", ".pdf", (("PDF", "*.pdf"),), Path(self.doc.path).stem + ".pdf")
        if not path or self._is_project(path):
            return
        try:
            from openschematix.export import export_project_pdf
            missing = export_project_pdf(self.doc.internal, path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Could not export: {exc}", parent=self.root)
            return
        self.toasts.show(f"Exported {Path(path).name}" + (f" ({len(missing)} characters replaced)" if missing else ""),
                         "success")

    def export_svg(self):
        if self.doc is None:
            return
        name = self.doc.sheet_names()[self.sheet]
        path = self._ask_save("Export sheet as SVG", ".svg", (("SVG", "*.svg"),), f"{Path(self.doc.path).stem} - {name}.svg")
        if not path or self._is_project(path):
            return
        try:
            from openschematix.export import export_svg
            export_svg(self.doc.sheet_doc(self.sheet), path, project=self.doc.internal)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Could not export: {exc}", parent=self.root)
            return
        self.toasts.show(f"Exported {Path(path).name}", "success")

    def export_bom(self):
        if self.doc is None:
            return
        path = self._ask_save("Export BOM", ".csv", (("CSV", "*.csv"),), Path(self.doc.path).stem + " BOM.csv")
        if not path or self._is_project(path):
            return
        try:
            Path(path).write_text(self.doc.api.bom_csv(), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not export: {exc}", parent=self.root)
            return
        self.toasts.show(f"Exported {Path(path).name}", "success")

    def _is_project(self, path: str) -> bool:
        """Exports never overwrite the open project file."""
        if self.doc and os.path.abspath(path) == os.path.abspath(self.doc.path):
            messagebox.showerror(APP_NAME, "That is the open project file. The viewer never changes it; choose "
                                           "another name.", parent=self.root)
            return True
        return False

    # ================================================================ RevisionWorx
    def _background(self, work, done):
        def run():
            try:
                self._jobs.put((done, work(), None))
            except Exception as exc:  # noqa: BLE001
                self._jobs.put((done, None, exc))
        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        try:
            while True:
                done, value, error = self._jobs.get_nowait()
                try:
                    done(value, error)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    @staticmethod
    def _probe_rwx():
        from .rwx_client import RevisionWorx
        rwx = RevisionWorx()
        return rwx if rwx.available() else None

    def _rwx_ready(self, rwx, _error):
        self.rwx = rwx or False
        state = "normal" if self.rwx else "disabled"
        for i in range(self.rwx_menu.index("end") + 1):
            self.rwx_menu.entryconfigure(i, state=state)
        if not self.rwx:
            self.rwx_open_btn.pack_forget()
            try:
                self.welcome_rwx_btn.pack_forget()
            except (AttributeError, tk.TclError):
                pass
        self.refresh_rwx()

    def refresh_rwx(self):
        if not self.rwx or self.doc is None:
            self._render_rwx()
            return
        path = self.doc.path
        self._background(lambda: self.rwx.status(path), self._rwx_status_done)

    def _rwx_status_done(self, status, error):
        self.rwx_status = status if error is None else {"error": str(error)}
        self._render_rwx()

    def rwx_summary(self) -> tuple[str, str]:
        """(text, tone) for the toolbar chip: tone is success, warning, info or muted."""
        if self.fetched:
            rev = self.fetched["revision"]
            doc = self.fetched.get("document") or {}
            latest = (doc.get("latest") or {}).get("label")
            text = f"{doc.get('number') or doc.get('title') or 'Document'} rev {rev['label']} · {rev['state_name']} · copy"
            if latest and latest != rev["label"]:
                return text + f" (latest is {latest})", "warning"
            return text, "success" if rev["state"] == "released" else "info"
        st = self.rwx_status
        if not st or self.doc is None:
            return "", "muted"
        if st.get("error"):
            return "RevisionWorx: status unavailable", "warning"
        if not st.get("controlled"):
            return "Not under revision control", "muted"
        from .rwx_client import describe
        text = describe(st)
        state = st["file"]["state"]
        latest = st["document"].get("latest") or {}
        if state not in ("unchanged",):
            return text, "warning"
        return text, "success" if latest.get("state") == "released" else "info"

    def _render_rwx(self):
        text, tone = self.rwx_summary()
        u = self.theme.ui
        if not text:
            self.rwx_chip.pack_forget()
            self.rwx_show_btn.pack_forget()
            return
        color = {"success": u["success"], "warning": u["warning"], "info": u["info"]}.get(tone, u["muted"])
        self.rwx_chip.configure(text=text, fg=color, bg=u["toolbar"])
        self.rwx_chip.pack(side="right", padx=6)
        controlled = bool(self.fetched) or bool(self.rwx_status and self.rwx_status.get("controlled"))
        if controlled and self.rwx:
            self.rwx_show_btn.pack(side="right", padx=1)
        else:
            self.rwx_show_btn.pack_forget()

    def show_rwx_status(self):
        text, _tone = self.rwx_summary()
        messagebox.showinfo("Revision status", text or "No file open, or RevisionWorx is not installed.",
                            parent=self.root)

    def show_in_rwx(self):
        if not self.rwx:
            return
        try:
            if self.fetched:
                self.rwx.open(document=self.fetched["document_id"])
            elif self.doc is not None:
                self.rwx.open(file=self.doc.path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)

    def open_from_rwx(self):
        if not self.rwx:
            messagebox.showinfo(APP_NAME, "RevisionWorx is not installed (or was not found). Install it to open "
                                          "controlled revisions here.", parent=self.root)
            return
        from .rwx_dialog import OpenFromRevisionWorx
        OpenFromRevisionWorx(self)

    def open_revision(self, doc: dict, revision: str | None = None, released: bool = False):
        """Copy one revision from RevisionWorx into a private cache folder and open it read-only."""
        cache = Path(tempfile.gettempdir()) / "openschematix-viewer" / doc["id"]
        try:
            got = self.rwx.fetch(doc["id"], str(cache), revision=revision, released=released)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return False
        got["document"] = doc
        return self.open_path(got["path"], fetched=got)

    # ================================================================ themes and dialogs
    def set_theme(self, name):
        self.theme = th.Theme(name)
        set_current_theme(self.theme)
        th.apply(self.root, self.theme)
        th.recolor_tree(self.root, self.theme)
        self.canvas.theme = self.theme
        self.canvas.font_family = self.theme.fonts.get("family", "Helvetica")
        self.canvas.redraw()
        self.theme_var.set(name)
        self.settings["theme"] = name
        self.settings.save()
        self.rwx_chip.configure(font=self.theme.fonts["small"])
        self._render_rwx()

    def cycle_theme(self):
        names = list(th.THEMES)
        self.set_theme(names[(names.index(self.theme.name) + 1) % len(names)] if self.theme.name in names else names[0])
        self.toasts.show(f"Theme: {self.theme.label}", "info", 1500)

    def show_shortcuts(self):
        win = tk.Toplevel(self.root)
        win.title("Keyboard shortcuts")
        win.configure(bg=self.theme.ui["surface"])
        frame = ttk.Frame(win, style="Surface.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        for i, (keys, what) in enumerate(SHORTCUTS):
            ttk.Label(frame, text=keys, style="Bold.TLabel").grid(row=i, column=0, sticky="w", padx=(0, 18), pady=2)
            ttk.Label(frame, text=what, style="Surface.TLabel").grid(row=i, column=1, sticky="w", pady=2)
        ttk.Button(frame, text="Close", command=win.destroy).grid(row=len(SHORTCUTS), column=1, sticky="e", pady=(12, 0))
        win.transient(self.root)
        self._dialog = win
        return win

    def show_about(self):
        t = self.theme
        win = tk.Toplevel(self.root)
        win.title(f"About {APP_NAME}")
        win.configure(bg=t.ui["surface"])
        f = ttk.Frame(win, style="Surface.TFrame", padding=20)
        f.pack(fill="both", expand=True)
        top = ttk.Frame(f, style="Surface.TFrame")
        top.pack(fill="x")
        if self.icon_image is not None:
            tk.Label(top, image=self.icon_image, bg=t.ui["surface"]).pack(side="left", padx=(0, 16))
        col = ttk.Frame(top, style="Surface.TFrame")
        col.pack(side="left", fill="x")
        ttk.Label(col, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(col, text=f"Version {VERSION}", style="Surface.TLabel").pack(anchor="w")
        ttk.Label(col, text="Read-only viewer for OpenSchematix projects", style="Muted.TLabel").pack(anchor="w")
        import openschematix
        body = (f"{COPYRIGHT}\n\n"
                f"Free and open-source software, licensed under the {LICENSE_NAME}. You may use, study, share and "
                "modify it under the terms of that licence. It comes with ABSOLUTELY NO WARRANTY.\n\n"
                f"Drawings are shown with OpenSchematix {openschematix.__version__}'s own renderer. The viewer "
                "never changes a project file. With RevisionWorx installed it shows each file's revision status "
                "and opens controlled revisions.\n\n"
                "No ads, no telemetry, no accounts and no feature limits. If it is useful to you, you can support "
                "its development voluntarily.")
        ttk.Label(f, text=body, style="Surface.TLabel", wraplength=520, justify="left").pack(anchor="w", pady=(16, 8))
        links = ttk.Frame(f, style="Surface.TFrame")
        links.pack(anchor="w")
        ttk.Button(links, text="Support development (Ko-fi)", style="Link.TButton",
                   command=lambda: webbrowser.open(DONATE_URL)).pack(side="left")
        ttk.Button(links, text="Project page", style="Link.TButton",
                   command=lambda: webbrowser.open(REPO_URL)).pack(side="left", padx=8)
        ttk.Button(links, text="Licence text", style="Link.TButton",
                   command=lambda: webbrowser.open(LICENSE_URL)).pack(side="left")
        ttk.Label(f, text=f"Python {platform.python_version()} · Tk {self.root.tk.call('info', 'patchlevel')} · "
                          f"{platform.system()} {platform.release()}", style="Faint.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Button(f, text="Close", command=win.destroy).pack(anchor="e", pady=(12, 0))
        win.transient(self.root)
        self._dialog = win
        return win

    def quit(self):
        try:
            self.settings["geometry"] = self.root.geometry()
            self.settings.save()
        except tk.TclError:
            pass
        self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("--version", "-V"):
        print(f"{APP_NAME} {VERSION}")
        return 0
    if len(argv) == 2 and argv[0] == "--self-test":
        from .selftest import run
        return run(Path(argv[1]))
    root = tk.Tk()
    ViewerApp(root, argv[0] if argv else None)
    root.mainloop()
    return 0
