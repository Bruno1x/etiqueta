"""Conservative visual reader for the light e-commerce grid shown in the recording."""
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class GridLayout:
    left: int
    top: int
    scale: float

    def point(self, x: float, y: float):
        return round(self.left + x * self.scale), round(self.top + y * self.scale)


@dataclass(frozen=True)
class GridRow:
    y: int
    green: bool
    printed: bool | None
    invoice_printed: bool | None
    selected: bool


class PrintGridReader:
    def __init__(self, asset_dir: Path):
        self.templates = {}
        for name in ('grid_header', 'print_button', 'print_button_hover', 'checked', 'unchecked'):
            image = cv2.imread(str(asset_dir / (name + '.png')), cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise RuntimeError(f'Referência de impressão ausente: {name}')
            self.templates[name] = image

    def locate(self, rgb, name, min_score=.94):
        gray = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2GRAY)
        template = self.templates[name]
        best = None
        for scale in (.8, .9, 1., 1.1, 1.25, 1.5):
            resized = cv2.resize(template, None, fx=scale, fy=scale)
            if resized.shape[0] > gray.shape[0] or resized.shape[1] > gray.shape[1]:
                continue
            _, score, _, point = cv2.minMaxLoc(cv2.matchTemplate(gray, resized, cv2.TM_CCOEFF_NORMED))
            if score >= min_score and (best is None or score > best[0]):
                best = score, point, scale
        return best

    def layout(self, rgb):
        result = self.locate(rgb, 'grid_header')
        if result is None:
            raise RuntimeError('Cabeçalhos da grade não reconhecidos. Use o layout claro da gravação, com Lib Etiqueta na primeira coluna.')
        _, (left, top), scale = result
        return GridLayout(left, top, scale)

    def checkbox(self, rgb, x, y, scale):
        gray = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2GRAY)
        radius = round(8 * scale)
        patch = gray[max(0, y-radius):y+radius+1, max(0, x-radius):x+radius+1]
        scores = {}
        for name in ('checked', 'unchecked'):
            template = cv2.resize(self.templates[name], None, fx=scale, fy=scale)
            if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
                return None
            scores[name] = float(cv2.minMaxLoc(cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED))[1])
        winner = max(scores, key=scores.get)
        loser = 'unchecked' if winner == 'checked' else 'checked'
        if scores[winner] < .94 or scores[winner] - scores[loser] < .06:
            return None
        return winner == 'checked'

    def rows(self, rgb, layout):
        array = np.asarray(rgb)
        x, start = layout.point(57, 21)
        radius = max(3, round(10 * layout.scale))
        strip = array[start:, max(0, x-radius):x+radius+1].astype(float)
        green = (strip[:, :, 1] > strip[:, :, 0] + 25) & (strip[:, :, 1] > strip[:, :, 2] + 20)
        red = (strip[:, :, 0] > strip[:, :, 1] + 55) & (strip[:, :, 0] > strip[:, :, 2] + 40)
        count, _, stats, centroids = cv2.connectedComponentsWithStats((green | red).astype('uint8'))
        result = []
        for index in range(1, count):
            _, _, width, height, area = stats[index]
            if not (7*layout.scale <= width <= 20*layout.scale and 7*layout.scale <= height <= 20*layout.scale and area > 35*layout.scale**2):
                continue
            local_y = round(float(centroids[index][1]))
            y = start + local_y
            patch = green[max(0, local_y-3):local_y+4]
            is_green = bool(patch.sum() >= 12 * layout.scale)
            label_x, _ = layout.point(575, 0)
            invoice_x, _ = layout.point(484, 0)
            selected_x, _ = layout.point(250, 0)
            color = array[y, selected_x].astype(float)
            selected = bool(color[2] > color[0] + 35 and color[2] > color[1] + 15)
            result.append(GridRow(y, is_green,
                                  self.checkbox(array, label_x, y, layout.scale),
                                  self.checkbox(array, invoice_x, y, layout.scale), selected))
        return sorted(result, key=lambda item: item.y)

    def print_point(self, rgb):
        result = self.locate(rgb, 'print_button', .90)
        if result is None:
            result = self.locate(rgb, 'print_button_hover', .94)
        if result is None:
            raise RuntimeError('Botão Etiqueta + Documentos não reconhecido; nada foi enviado.')
        _, (x, y), scale = result
        return round(x + 82*scale), round(y + 27*scale)
