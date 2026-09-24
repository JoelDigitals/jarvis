"""Umschaltbares Datenverzeichnis für config/, memory/, content/, music/.

Desktop-JARVIS: zeigt immer auf den Projektordner (Verhalten wie bisher).
Web-App: pro Tool-Aufruf wird das Datenverzeichnis des jeweiligen Benutzers gesetzt
(`use_data_root`). Da contextvars pro Thread/Task gelten, können mehrere Benutzer
gleichzeitig Tools ausführen, ohne sich gegenseitig die Einstellungen zu überschreiben.
"""
from __future__ import annotations

import contextvars
import os
import sys
from contextlib import contextmanager
from pathlib import Path


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _project_root()
_data_root: contextvars.ContextVar[Path | None] = contextvars.ContextVar("jarvis_data_root", default=None)


def data_root() -> Path:
    return _data_root.get() or PROJECT_ROOT


@contextmanager
def use_data_root(path: Path | str | None):
    token = _data_root.set(Path(path) if path else None)
    try:
        yield
    finally:
        _data_root.reset(token)


class DataPath(os.PathLike):
    """Verhält sich wie ein Path, wird aber bei jedem Zugriff gegen data_root() aufgelöst."""

    __slots__ = ("_parts",)

    def __init__(self, *parts: str):
        self._parts = tuple(str(p) for p in parts)

    def resolve_now(self) -> Path:
        return data_root().joinpath(*self._parts)

    def __fspath__(self) -> str:
        return str(self.resolve_now())

    def __str__(self) -> str:
        return str(self.resolve_now())

    def __repr__(self) -> str:
        return f"DataPath({'/'.join(self._parts)!r} → {self.resolve_now()})"

    def __truediv__(self, other) -> "DataPath":
        return DataPath(*self._parts, str(other))

    def __eq__(self, other) -> bool:
        return Path(self) == Path(other) if isinstance(other, (str, os.PathLike)) else NotImplemented

    def __hash__(self) -> int:
        return hash(self.resolve_now())

    def __getattr__(self, name):
        return getattr(self.resolve_now(), name)
