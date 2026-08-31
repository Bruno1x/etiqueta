from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import socket
import time
from typing import Any

from .config import AppConfig, Step
from .reference import ReferenceScreenMatcher
from .windows import (
    activate_and_maximize,
    find_unique_window,
    restore_taskbars,
    screen_metrics,
    virtual_screen_metrics,
)


@dataclass(frozen=True)
class AnchorSpec:
    name: str
    label: str


@dataclass(frozen=True)
class LocatedAnchor:
    name: str
    x: int
    y: int
    score: float
    width: int
    height: int


@dataclass(frozen=True)
class CalibrationResult:
    status: str
    profile_path: Path
    detected: tuple[LocatedAnchor, ...]
    missing: tuple[AnchorSpec, ...]
    message: str


def machine_id() -> str:
    value = socket.gethostname().strip() or "computador"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


class CalibrationManager:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.profile_dir = config.root / "runtime" / "profiles" / machine_id()
        self.profile_path = self.profile_dir / "calibration.json"
        self.anchor_dir = self.profile_dir / "anchors"
        self.reference_matcher = ReferenceScreenMatcher(config)

    def reference_pack_ready(self) -> bool:
        return self.reference_matcher.is_ready()

    def anchor_specs(self) -> tuple[AnchorSpec, ...]:
        result: list[AnchorSpec] = []
        seen: set[str] = set()
        for workflow in self.config.workflows.values():
            for step in workflow.steps:
                if step.action == "click" and step.anchor and step.anchor not in seen:
                    seen.add(step.anchor)
                    result.append(AnchorSpec(step.anchor, step.label))
        return tuple(result)

    def load_profile(self) -> dict[str, Any]:
        if not self.profile_path.exists():
            return {}
        return json.loads(self.profile_path.read_text(encoding="utf-8"))

    def _save_profile(self, profile: dict[str, Any]) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _target_window(self):
        target = self.config.target_window
        return find_unique_window(
            title_regex=target.get("title_regex"),
            process_path_regex=target.get("process_path_regex"),
        )

    def base_profile(self) -> dict[str, Any]:
        metrics = screen_metrics()
        virtual = virtual_screen_metrics()
        window = self._target_window()
        return {
            "schema_version": 1,
            "machine": machine_id(),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "monitor": {
                "width": metrics.width,
                "height": metrics.height,
                "dpi": metrics.dpi,
                "scale_percent": metrics.scale_percent,
                "virtual_left": virtual.left,
                "virtual_top": virtual.top,
                "virtual_width": virtual.width,
                "virtual_height": virtual.height,
                "monitor_count": virtual.monitor_count,
            },
            "window": {
                "title": window.title,
                "process_path": window.process_path,
                "left": window.left,
                "top": window.top,
                "width": window.width,
                "height": window.height,
            },
            "anchors": self.load_profile().get("anchors", {}),
        }

    def capture_anchor_at(self, spec: AnchorSpec, x: int, y: int) -> Path:
        import pyautogui
        from PIL import ImageGrab

        width = int(self.config.safety["guided_capture_width"])
        height = int(self.config.safety["guided_capture_height"])
        virtual = virtual_screen_metrics()
        right_limit = virtual.left + virtual.width
        bottom_limit = virtual.top + virtual.height
        left = max(virtual.left, min(x - width // 2, right_limit - width))
        top = max(virtual.top, min(y - height // 2, bottom_limit - height))
        click_offset_x = x - left
        click_offset_y = y - top

        pyautogui.moveTo(8, 8, duration=0.15)
        time.sleep(0.25)
        image = ImageGrab.grab(
            bbox=(left, top, left + width, top + height),
            all_screens=True,
        )
        self.anchor_dir.mkdir(parents=True, exist_ok=True)
        path = self.anchor_dir / spec.name
        image.save(path)

        profile = self.base_profile()
        profile["anchors"][spec.name] = {
            "file": f"anchors/{spec.name}",
            "captured_x": x,
            "captured_y": y,
            "click_offset_x": click_offset_x,
            "click_offset_y": click_offset_y,
            "width": width,
            "height": height,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save_profile(profile)
        return path

    def anchor_path(self, name: str) -> Path | None:
        profile = self.load_profile()
        item = profile.get("anchors", {}).get(name)
        if item:
            candidate = self.profile_dir / item["file"]
            if candidate.exists():
                return candidate
        generic = self.config.root / "assets" / "anchors" / name
        return generic if generic.exists() else None

    def locate_anchor(
        self,
        name: str,
        region: tuple[int, int, int, int] | None = None,
        min_score: float | None = None,
    ) -> LocatedAnchor | None:
        import cv2
        import numpy as np
        from PIL import ImageGrab

        template_path = self.anchor_path(name)
        if name.startswith("channels/") and region is not None:
            from .channel_vision import locate_light_channel
            reference = self.config.root / "assets/reference_screens/ecommerce_channels_light.png"
            if reference.exists():
                pixels = np.asarray(ImageGrab.grab(bbox=region, all_screens=True).convert("RGB"))
                found = locate_light_channel(reference, Path(name).stem, pixels)
                if found is not None:
                    score, left, top, width, height = found
                    return LocatedAnchor(name, region[0] + left + width // 2,
                                         region[1] + top + height // 2,
                                         score, width, height)
        if template_path is None:
            return None
        virtual = virtual_screen_metrics()
        screenshot = cv2.cvtColor(
            np.array(ImageGrab.grab(all_screens=True)), cv2.COLOR_RGB2GRAY
        )
        region_left = 0
        region_top = 0
        if region is not None:
            absolute_left, absolute_top, absolute_right, absolute_bottom = region
            region_left = max(0, absolute_left - virtual.left)
            region_top = max(0, absolute_top - virtual.top)
            region_right = min(screenshot.shape[1], absolute_right - virtual.left)
            region_bottom = min(screenshot.shape[0], absolute_bottom - virtual.top)
            if region_right <= region_left or region_bottom <= region_top:
                return None
            screenshot = screenshot[region_top:region_bottom, region_left:region_right]
        template_original = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if template_original is None:
            return None

        best: tuple[float, tuple[int, int], int, int] | None = None
        for scale in (0.70, 0.80, 0.90, 1.0, 1.10, 1.20, 1.35, 1.50):
            width = round(template_original.shape[1] * scale)
            height = round(template_original.shape[0] * scale)
            if width < 12 or height < 12:
                continue
            if width > screenshot.shape[1] or height > screenshot.shape[0]:
                continue
            template = cv2.resize(
                template_original,
                (width, height),
                interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
            )
            response = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(response)
            if best is None or score > best[0]:
                best = (float(score), location, width, height)

        required_score = (
            float(min_score)
            if min_score is not None
            else float(self.config.safety["confidence"])
        )
        if best is None or best[0] < required_score:
            return None
        score, (left, top), width, height = best
        profile_item = self.load_profile().get("anchors", {}).get(name, {})
        original_width = max(1, int(profile_item.get("width", width)))
        original_height = max(1, int(profile_item.get("height", height)))
        offset_x = int(profile_item.get("click_offset_x", original_width // 2))
        offset_y = int(profile_item.get("click_offset_y", original_height // 2))
        x = (
            virtual.left
            + region_left
            + left
            + round(offset_x * width / original_width)
        )
        y = (
            virtual.top
            + region_top
            + top
            + round(offset_y * height / original_height)
        )
        return LocatedAnchor(name, x, y, score, width, height)

    def auto_calibrate(self) -> CalibrationResult:
        try:
            return self._auto_calibrate_impl()
        finally:
            restore_taskbars()

    def _auto_calibrate_impl(self) -> CalibrationResult:
        window = self._target_window()
        if self.config.target_window["maximize_before_run"]:
            activate_and_maximize(window)
            time.sleep(0.8)

        if not self.reference_matcher.is_ready():
            raise RuntimeError("O pacote automático de referências está incompleto.")
        visible_screen = self.reference_matcher.detect_visible_screen()
        profile = self.base_profile()
        profile["status"] = "ready" if visible_screen else "partial"
        profile["reference_pack_version"] = self.reference_matcher.version
        profile["last_auto_calibration"] = {
            "visible_screen": visible_screen.screen_id if visible_screen else None,
            "confidence": visible_screen.confidence if visible_screen else None,
            "inliers": visible_screen.inliers if visible_screen else None,
        }
        self._save_profile(profile)
        if visible_screen:
            message = (
                "Autocalibração automática concluída. "
                f"Tela reconhecida: {visible_screen.screen_id}; "
                f"confiança {visible_screen.confidence:.0%}."
            )
        else:
            message = (
                "Pacote automático instalado, mas a tela atual não corresponde às "
                "cinco referências. Abra uma das telas do fluxo e tente novamente."
            )
        return CalibrationResult(
            profile["status"], self.profile_path, tuple(), tuple(), message
        )

    def validate_all(self) -> CalibrationResult:
        if self.reference_matcher.is_ready():
            visible = self.reference_matcher.detect_visible_screen()
            if visible:
                return CalibrationResult(
                    "ready",
                    self.profile_path,
                    tuple(),
                    tuple(),
                    f"Tela reconhecida automaticamente: {visible.screen_id}; "
                    f"confiança {visible.confidence:.0%}.",
                )
            return CalibrationResult(
                "partial",
                self.profile_path,
                tuple(),
                tuple(),
                "Nenhuma das cinco telas de referência está visível.",
            )

        detected: list[LocatedAnchor] = []
        missing: list[AnchorSpec] = []
        for spec in self.anchor_specs():
            if self.anchor_path(spec.name) is None:
                missing.append(spec)
                continue
            item = self.locate_anchor(spec.name)
            if item:
                detected.append(item)
        status = "ready" if not missing else "partial"
        return CalibrationResult(
            status,
            self.profile_path,
            tuple(detected),
            tuple(missing),
            f"Tela atual: {len(detected)} reconhecidos; "
            f"{len(missing)} referências ainda não capturadas.",
        )
