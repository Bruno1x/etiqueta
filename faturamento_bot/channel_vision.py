"""Text-only, polarity-independent references for the supplied light checklist."""
from pathlib import Path


# Full text bounds, excluding checkbox, scrollbar and adjacent rows.
LIGHT_ROWS = {
    'ml_central': (163, 222, 239, 236),
    'ml_distribuidor': (163, 239, 279, 253),
    'ml_fabrica': (163, 256, 241, 270),
    'ml_hero_band': (163, 273, 263, 287),
    'ml_poolsy': (163, 290, 239, 304),
    'ml_shopping': (163, 307, 259, 321),
}

BOTTOM_ROWS = {
    'ml_store': (163, 256, 229, 270),
    'ml_universo': (163, 273, 249, 287),
}


def text_mask(image):
    import cv2
    import numpy as np
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    # Both white text on blue and black text on white produce foreground=255.
    background = np.median(gray, axis=1, keepdims=True)
    return (np.abs(gray.astype(float) - background) > 65).astype('uint8') * 255


def locate_light_channel(reference_path: Path, slug: str, rgb, min_score=.80):
    import cv2
    import numpy as np
    from PIL import Image
    bounds = LIGHT_ROWS.get(slug)
    if slug in BOTTOM_ROWS:
        bounds = BOTTOM_ROWS[slug]
        reference_path = reference_path.with_name('ecommerce_channels_light_bottom.png')
    if bounds is None:
        return None
    with Image.open(reference_path) as source:
        row = np.asarray(source.convert('RGB').crop((144, bounds[1], 540, bounds[3])))
        template = text_mask(row)[:, bounds[0] - 144:bounds[2] - 144]
    search = text_mask(rgb)
    best = None
    for scale in (.8, .9, 1., 1.1, 1.25, 1.5):
        width, height = round(template.shape[1] * scale), round(template.shape[0] * scale)
        if width > search.shape[1] or height > search.shape[0]:
            continue
        resized = cv2.resize(template, (width, height), interpolation=cv2.INTER_NEAREST)
        scores = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
        _, score, _, point = cv2.minMaxLoc(scores)
        if score >= min_score and (best is None or score > best[0]):
            best = (score, point[0], point[1], width, height)
    return best
