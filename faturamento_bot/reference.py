from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import time
import tomllib
import unicodedata

from .config import AppConfig
from .windows import foreground_window_info, virtual_screen_metrics


@dataclass(frozen=True)
class ReferencePoint:
    screen_id: str
    x: int
    y: int
    confidence: float
    inliers: int


@dataclass(frozen=True)
class ScreenMatch:
    screen_id: str
    homography: object
    confidence: float
    inliers: int


class ReferenceScreenMatcher:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        manifest_path = config.root / "config" / "reference_screens.toml"
        with manifest_path.open("rb") as stream:
            self.manifest = tomllib.load(stream)
        self.reference_dir = config.root / "assets" / "reference_screens"
        self._reference_features: dict[str, tuple[object, object, tuple[int, int]]] = {}

    @property
    def version(self) -> int:
        return int(self.manifest["reference_pack"]["version"])

    def is_ready(self) -> bool:
        screens = self.manifest.get("screens", {})
        return bool(screens) and all(
            (self.reference_dir / item["file"]).exists() for item in screens.values()
        )

    def screen_ids(self) -> tuple[str, ...]:
        return tuple(key for key, value in self.manifest.get("screens", {}).items()
                     if "canonical_screen" not in value)

    def _detector(self):
        import cv2

        return cv2.SIFT_create(nfeatures=3500, contrastThreshold=0.025)

    def _reference(self, screen_id: str):
        import cv2

        cached = self._reference_features.get(screen_id)
        if cached is not None:
            return cached
        screen = self.manifest["screens"][screen_id]
        image = cv2.imread(
            str(self.reference_dir / screen["file"]),
            cv2.IMREAD_GRAYSCALE,
        )
        if image is None:
            raise RuntimeError(f"Referência visual ausente: {screen['file']}")
        keypoints, descriptors = self._detector().detectAndCompute(image, None)
        if descriptors is None or len(keypoints) < 10:
            raise RuntimeError(f"Referência visual insuficiente: {screen['file']}")
        result = (keypoints, descriptors, (image.shape[1], image.shape[0]))
        self._reference_features[screen_id] = result
        return result

    def _desktop_features(self):
        import cv2
        import numpy as np
        from PIL import ImageGrab

        rgb = np.array(ImageGrab.grab(all_screens=True))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        keypoints, descriptors = self._detector().detectAndCompute(gray, None)
        return keypoints, descriptors, gray.shape

    def match(self, screen_id: str, desktop_features=None) -> ScreenMatch | None:
        features = desktop_features or self._desktop_features()
        candidates = [screen_id] + [
            key for key, value in self.manifest["screens"].items()
            if value.get("canonical_screen") == screen_id
        ]
        matches = [self._match_single(key, features) for key in candidates]
        visual = max((item for item in matches if item is not None),
                     key=lambda item: item.confidence, default=None)
        if visual is not None:
            return visual
        if screen_id == "ecommerce_manager":
            return self._manager_geometry_match()
        return None

    def _manager_geometry_match(self) -> ScreenMatch | None:
        """Recognize the manager by its Windows identity, independent of skin colors."""
        import numpy as np

        try:
            window, class_name = foreground_window_info()
        except RuntimeError:
            return None
        title = "".join(
            char for char in unicodedata.normalize("NFKD", window.title)
            if not unicodedata.combining(char)
        ).casefold().strip()
        manager_title = re.match(
            r"^(?:\[0682\]\s*)?gerenciador de impressoes d[eo] e-commerce\s*$",
            title,
        )
        process_pattern = self.config.target_window.get("process_path_regex")
        if (class_name == "#32770" or not manager_title
                or not process_pattern or not re.search(process_pattern, window.process_path)):
            return None
        if window.width < 900 or window.height < 600:
            return None

        # The SYSEMP keeps the manager's logical canvas at a 16:9 proportion.
        # Use window width so the reserved taskbar area does not compress Y.
        scale = window.width / 1920.0
        if not 0.55 <= scale <= 1.80:
            return None
        virtual = virtual_screen_metrics()
        homography = np.asarray([
            [scale, 0.0, float(window.left - virtual.left)],
            [0.0, scale, float(window.top - virtual.top)],
            [0.0, 0.0, 1.0],
        ])
        return ScreenMatch("ecommerce_manager", homography, 1.0, 0)

    def _match_single(self, screen_id: str, desktop_features) -> ScreenMatch | None:
        import cv2
        import numpy as np

        reference_keypoints, reference_descriptors, reference_size = self._reference(
            screen_id
        )
        desktop_keypoints, desktop_descriptors, desktop_shape = (
            desktop_features or self._desktop_features()
        )
        if desktop_descriptors is None or len(desktop_keypoints) < 10:
            return None

        matcher = cv2.FlannBasedMatcher(
            dict(algorithm=1, trees=5),
            dict(checks=64),
        )
        pairs = matcher.knnMatch(reference_descriptors, desktop_descriptors, k=2)
        good = [pair[0] for pair in pairs
                if len(pair) == 2 and pair[0].distance < 0.72 * pair[1].distance]
        if len(good) < 8:
            return None

        source = np.float32(
            [reference_keypoints[item.queryIdx].pt for item in good]
        ).reshape(-1, 1, 2)
        destination = np.float32(
            [desktop_keypoints[item.trainIdx].pt for item in good]
        ).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(
            source,
            destination,
            cv2.RANSAC,
            5.0,
        )
        if homography is None or mask is None:
            return None
        inliers = int(mask.ravel().sum())
        inlier_ratio = inliers / max(1, len(good))
        requirements = self.manifest["screens"][screen_id]
        if inliers < int(requirements["min_inliers"]):
            return None
        if inlier_ratio < float(requirements["min_inlier_ratio"]):
            return None

        width, height = reference_size
        corners = np.float32(
            [[[0, 0]], [[width, 0]], [[width, height]], [[0, height]]]
        )
        mapped = cv2.perspectiveTransform(corners, homography).reshape(-1, 2)
        mapped_width = float(
            (np.linalg.norm(mapped[1] - mapped[0]) + np.linalg.norm(mapped[2] - mapped[3]))
            / 2
        )
        mapped_height = float(
            (np.linalg.norm(mapped[3] - mapped[0]) + np.linalg.norm(mapped[2] - mapped[1]))
            / 2
        )
        scale_x = mapped_width / max(1, width)
        scale_y = mapped_height / max(1, height)
        if not (0.55 <= scale_x <= 1.80 and 0.55 <= scale_y <= 1.80):
            return None
        if max(scale_x, scale_y) / min(scale_x, scale_y) > 1.18:
            return None

        confidence = min(1.0, inlier_ratio * min(1.0, inliers / 40))
        canonical = requirements.get("canonical_screen", screen_id)
        if "canonical_transform" in requirements:
            transform = np.asarray(requirements["canonical_transform"], dtype=float).reshape(3, 3)
            homography = homography @ transform
        return ScreenMatch(canonical, homography, confidence, inliers)

    def locate_point(
        self,
        screen_id: str,
        reference_x: int,
        reference_y: int,
        timeout_seconds: float = 12.0,
    ) -> ReferencePoint | None:
        import cv2
        import numpy as np

        deadline = time.monotonic() + timeout_seconds
        while True:
            matched = self.match(screen_id)
            if matched is not None:
                point = np.float32([[[reference_x, reference_y]]])
                mapped = cv2.perspectiveTransform(point, matched.homography)[0, 0]
                virtual = virtual_screen_metrics()
                return ReferencePoint(
                    screen_id=screen_id,
                    x=virtual.left + round(float(mapped[0])),
                    y=virtual.top + round(float(mapped[1])),
                    confidence=matched.confidence,
                    inliers=matched.inliers,
                )
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.5)

    def map_point(
        self,
        matched: ScreenMatch,
        reference_x: int,
        reference_y: int,
    ) -> ReferencePoint:
        import cv2
        import numpy as np

        point = np.float32([[[reference_x, reference_y]]])
        mapped = cv2.perspectiveTransform(point, matched.homography)[0, 0]
        virtual = virtual_screen_metrics()
        return ReferencePoint(
            screen_id=matched.screen_id,
            x=virtual.left + round(float(mapped[0])),
            y=virtual.top + round(float(mapped[1])),
            confidence=matched.confidence,
            inliers=matched.inliers,
        )

    def detect_visible_screen(self) -> ScreenMatch | None:
        # Window identity is stronger than skin-dependent image similarity and
        # prevents the manager from being mistaken for the e-Commerce home.
        manager = self._manager_geometry_match()
        if manager is not None:
            return manager
        desktop_features = self._desktop_features()
        best: ScreenMatch | None = None
        for screen_id in self.screen_ids():
            if "canonical_screen" in self.manifest["screens"][screen_id]:
                continue
            matched = self.match(screen_id, desktop_features)
            if matched and (best is None or matched.confidence > best.confidence):
                best = matched
        return best
