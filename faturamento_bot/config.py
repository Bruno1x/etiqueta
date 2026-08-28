from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any


@dataclass(frozen=True)
class MonitorProfile:
    physical_width: int
    physical_height: int
    logical_width: int
    logical_height: int
    dpi: int
    scale_percent: int


@dataclass(frozen=True)
class Step:
    id: str
    action: str
    label: str
    anchor: str | None = None
    x_ratio: float | None = None
    y_ratio: float | None = None
    value: str | None = None
    pause_seconds: float | None = None
    screen_id: str | None = None
    reference_x: int | None = None
    reference_y: int | None = None


@dataclass(frozen=True)
class Workflow:
    name: str
    description: str
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class AppConfig:
    root: Path
    raw: dict[str, Any]
    monitor: MonitorProfile
    workflows: dict[str, Workflow]

    @property
    def safety(self) -> dict[str, Any]:
        return self.raw["safety"]

    @property
    def target_window(self) -> dict[str, Any]:
        return self.raw["target_window"]

    @property
    def patrol(self) -> dict[str, Any]:
        return self.raw["patrol"]

    @property
    def processing(self) -> dict[str, Any]:
        return self.raw["processing"]


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "faturamento.toml"


def load_config(path: Path | None = None) -> AppConfig:
    config_path = (path or default_config_path()).resolve()
    with config_path.open("rb") as stream:
        raw = tomllib.load(stream)

    monitor = MonitorProfile(**raw["monitor"])
    workflows: dict[str, Workflow] = {}
    for name, item in raw["workflows"].items():
        steps = tuple(Step(**step) for step in item["steps"])
        workflows[name] = Workflow(name, item["description"], steps)

    return AppConfig(
        root=config_path.parents[1],
        raw=raw,
        monitor=monitor,
        workflows=workflows,
    )
