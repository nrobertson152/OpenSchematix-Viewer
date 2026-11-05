# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-user viewer settings (theme, recent files, window size). Damage reads as defaults; failing to save
never stops the viewer."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

DEFAULTS = {"theme": "modern_light", "recent": [], "geometry": "", "sidebar": True}


def config_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "OpenSchematix Viewer"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "openschematix-viewer"


class Settings:
    def __init__(self, folder: Path | None = None):
        self.folder = Path(folder) if folder else config_dir()
        self.path = self.folder / "settings.json"
        self.data = dict(DEFAULTS)
        self.warning: str | None = None
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update({k: v for k, v in loaded.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass
        if not isinstance(self.data.get("recent"), list):
            self.data["recent"] = []

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value

    def remember(self, path: str) -> None:
        recent = [path] + [p for p in self.data["recent"] if p != path and isinstance(p, str)]
        self.data["recent"] = recent[:10]
        self.save()

    def save(self) -> bool:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".settings-", dir=self.folder)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self.path)
            self.warning = None
            return True
        except OSError as exc:
            self.warning = f"Settings could not be saved in {self.folder}: {exc.strerror or exc}"
            return False
