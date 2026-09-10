from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ModelKind = Literal["model", "projector", "checkpoint", "unknown"]


@dataclass(frozen=True)
class ModelFile:
    path: Path
    name: str
    size_bytes: int
    modified_ns: int
    kind: ModelKind


@dataclass(frozen=True)
class RuntimeState:
    id: str
    label: str
    configured: bool
    exists: bool
    path: str | None
    launchable: bool
    running: bool = False
    pid: int | None = None
    recovered: bool = False
