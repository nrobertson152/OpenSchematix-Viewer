# SPDX-License-Identifier: GPL-3.0-or-later
"""The opened project, as the viewer needs it. No GUI toolkit here, so it is fully testable headless.

Data (components, BOM, nets, title block) comes from OpenSchematix's public scripting API
(``openschematix.api``). Drawing uses the application's own renderer (``openschematix.render``), so a sheet
looks exactly as it does in OpenSchematix. The file is opened read-only and never written."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ViewerError(Exception):
    """A file could not be shown. The message is meant for the user."""


@dataclass(frozen=True)
class ComponentRow:
    sheet_index: int
    sheet: str
    id: int
    designator: str
    symbol: str
    description: str
    part_number: str
    manufacturer: str
    rating: str
    label: str
    terminals: tuple[str, ...]
    properties: tuple[tuple[str, str], ...]

    @property
    def title(self) -> str:
        return " ".join(x for x in (self.designator, self.description or self.symbol) if x) or self.symbol

    def text(self) -> str:
        return " ".join((self.designator, self.symbol, self.description, self.part_number, self.manufacturer,
                         self.rating, self.label, self.sheet, *[v for _, v in self.properties])).casefold()


META_LABELS = (("title", "Title"), ("number", "Drawing number"), ("revision", "Revision"), ("client", "Client"),
               ("organisation", "Organisation"), ("author", "Drawn by"), ("checked_by", "Checked by"),
               ("approved_by", "Approved by"), ("date", "Date"), ("description", "Description"))


class ViewerDocument:
    def __init__(self, path: str | os.PathLike):
        from openschematix import api
        self.path = str(Path(path).resolve())
        try:
            self.api = api.open_project(self.path)
        except api.ApiError as exc:
            raise ViewerError(str(exc)) from exc
        except OSError as exc:
            raise ViewerError(f"could not open {path}: {exc.strerror or exc}") from exc
        self.warnings = tuple(self.api.warnings)
        self._components: list[ComponentRow] | None = None

    # ---------------------------------------------------------------- structure
    @property
    def internal(self):
        """OpenSchematix's own project object, with this project's symbols active (for drawing)."""
        return self.api._use()

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def title(self) -> str:
        return self.api.title or Path(self.path).stem

    def sheet_names(self) -> list[str]:
        return [s.name for s in self.api.sheets]

    def sheet_doc(self, index: int):
        return self.internal.sheets[index]

    def meta(self) -> list[tuple[str, str]]:
        m = self.internal.meta
        return [(label, m.get(key, "")) for key, label in META_LABELS if m.get(key)]

    # ---------------------------------------------------------------- components
    def components(self) -> list[ComponentRow]:
        if self._components is None:
            from openschematix import api
            rows = []
            for si, sheet in enumerate(self.api.sheets):
                for c in sheet.components():
                    try:
                        name = api.get_symbol(c.symbol_id).name
                    except api.ApiError:
                        name = c.symbol_id
                    props = dict(c.properties)
                    rows.append(ComponentRow(si, sheet.name, c.id, c.designator, name, props.get("description", ""),
                                             props.get("part_number", ""), props.get("manufacturer", ""),
                                             props.get("rating", ""), c.label, tuple(c.terminals),
                                             tuple(sorted(props.items()))))
            self._components = rows
        return self._components

    def search(self, text: str) -> list[ComponentRow]:
        words = text.casefold().split()
        rows = self.components()
        if not words:
            return [r for r in rows if r.designator or r.description]
        return [r for r in rows if all(w in r.text() for w in words)]

    def component(self, sheet_index: int, cid: int) -> ComponentRow | None:
        return next((r for r in self.components() if r.sheet_index == sheet_index and r.id == cid), None)

    # ---------------------------------------------------------------- reports
    def bom(self) -> list:
        return self.api.bom()

    def nets(self) -> list[dict]:
        out = []
        for n in self.api.nets():
            ends = [f"{t.designator or '?'}:{t.terminal}" for t in n.terminals]
            sheets = sorted({t.sheet_name for t in n.terminals})
            out.append({"number": n.number, "terminals": ends, "sheets": sheets,
                        "sheet_uids": list(n.sheets), "refs": n.terminals})
        out.sort(key=lambda n: (_natural(n["number"]) if n["number"] else (1, ""), n["terminals"]))
        return out

    # ---------------------------------------------------------------- geometry (hit testing)
    def component_bbox(self, sheet_index: int, cid: int):
        from openschematix.render import component_prims, scene_bbox
        doc = self.sheet_doc(sheet_index)
        for comp in doc.components.values() if isinstance(doc.components, dict) else doc.components:
            if comp.id == cid:
                return scene_bbox(component_prims(comp))
        return None

    def component_at(self, sheet_index: int, point, tolerance: float = 4.0) -> int | None:
        """The component under a world point (the smallest one if several overlap), or None."""
        from openschematix.render import component_prims, scene_bbox
        doc = self.sheet_doc(sheet_index)
        comps = doc.components.values() if isinstance(doc.components, dict) else doc.components
        best = None
        for comp in comps:
            b = scene_bbox(component_prims(comp))
            if not b:
                continue
            x0, y0, x1, y1 = b
            if x0 - tolerance <= point[0] <= x1 + tolerance and y0 - tolerance <= point[1] <= y1 + tolerance:
                area = (x1 - x0) * (y1 - y0)
                if best is None or area < best[0]:
                    best = (area, comp.id)
        return best[1] if best else None

    def sheet_size(self, index: int) -> tuple[float, float]:
        return self.sheet_doc(index).sheet.size_units()


def _natural(s: str):
    import re
    return (0, [int(p) if p.isdigit() else p.casefold() for p in re.split(r"(\d+)", s)])
