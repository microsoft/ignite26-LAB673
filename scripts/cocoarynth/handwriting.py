"""Simulated handwriting and paper-scan effects for Cocoarynth's scanned forms and notes."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).resolve().parents[2] / "data" / "cocoarynth" / "assets" / "fonts"
BLUE_BALLPOINT = (24, 40, 118)
BLACK_PEN = (32, 32, 38)
RED_MARKER = (178, 34, 38)


@dataclass(frozen=True)
class Hand:
    """One person's handwriting: font plus how irregular it is."""

    font: str
    size: int
    ink: tuple[int, int, int] = BLUE_BALLPOINT
    slant: float = 0.0
    wobble: float = 2.0
    jitter_deg: float = 2.5
    spacing: float = 1.0
    size_jitter: float = 0.05


class Writer:
    """Accumulates handwriting on a transparent ink layer the size of the page."""

    def __init__(self, size: tuple[int, int], seed: int):
        self.layer = Image.new("RGBA", size, (0, 0, 0, 0))
        self.rng = np.random.default_rng(seed)
        self._fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    def font(self, hand: Hand, size: int) -> ImageFont.FreeTypeFont:
        key = (hand.font, size)
        if key not in self._fonts:
            self._fonts[key] = ImageFont.truetype(str(FONTS / hand.font), size)
        return self._fonts[key]

    def measure(self, text: str, hand: Hand) -> float:
        return self.font(hand, hand.size).getlength(text) * hand.spacing

    def write(self, text: str, x: float, baseline: float, hand: Hand, tilt: float | None = None) -> float:
        """Write text starting at x on the given baseline; returns the x position after the last character."""
        rng = self.rng
        tilt = rng.normal(0, 0.7) if tilt is None else tilt
        slope = np.tan(np.radians(tilt))
        drift = 0.0
        cx = x + rng.normal(0, 1.5)
        for ch in text:
            size = max(8, round(hand.size * (1 + rng.normal(0, hand.size_jitter))))
            font = self.font(hand, size)
            advance = font.getlength(ch) * hand.spacing * (1 + rng.normal(0, 0.035))
            drift = 0.65 * drift + rng.normal(0, hand.wobble * 0.55)
            y = baseline + drift - (cx - x) * slope
            if not ch.isspace():
                alpha = int(np.clip(rng.normal(232, 14), 170, 255))
                glyph, origin = self._glyph(ch, font, hand.ink, alpha)
                glyph = glyph.rotate(-hand.slant + rng.normal(0, hand.jitter_deg), resample=Image.BICUBIC, center=origin)
                self.layer.alpha_composite(glyph, (int(round(cx - origin[0])), int(round(y - origin[1]))))
            cx += advance + rng.normal(0, 0.5)
        return cx

    def write_wrapped(self, text: str, x: float, baseline: float, width: float, line_height: float, hand: Hand) -> float:
        """Write text wrapped to width; returns the baseline of the last line."""
        line = ""
        for word in text.split():
            candidate = f"{line} {word}".strip()
            if line and self.measure(candidate, hand) > width:
                self.write(line, x, baseline, hand, tilt=self.rng.normal(0, 0.25))
                baseline += line_height
                line = word
            else:
                line = candidate
        if line:
            self.write(line, x, baseline, hand, tilt=self.rng.normal(0, 0.25))
        return baseline

    def underline(self, x0: float, x1: float, y: float, hand: Hand, width: int = 3) -> None:
        draw = ImageDraw.Draw(self.layer)
        points = [(x, y + self.rng.normal(0, 1.2) + (x - x0) * 0.01) for x in np.linspace(x0, x1, 8)]
        draw.line(points, fill=(*hand.ink, 220), width=width, joint="curve")

    @staticmethod
    def _glyph(ch: str, font: ImageFont.FreeTypeFont, ink, alpha: int):
        size = font.size
        pad = int(size * 0.7)
        width = int(font.getlength(ch)) + 2 * pad
        height = int(size * 2.4)
        baseline = int(size * 1.55)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(image).text((pad, baseline), ch, font=font, fill=(*ink, alpha), anchor="ls")
        return image, (pad, baseline)

    def finish(self, roughness: float = 1.4) -> Image.Image:
        """Warp and texture the ink so strokes look pen-drawn rather than typeset."""
        layer = elastic(self.layer, amplitude=roughness, cell=14, rng=self.rng)
        pixels = np.asarray(layer).astype(np.float32)
        h, w = pixels.shape[:2]
        pressure = smooth_noise((h, w), cell=60, rng=self.rng) * 0.18 + 0.92
        grain = self.rng.uniform(0.8, 1.0, (h, w))
        pixels[..., 3] *= np.clip(pressure * grain, 0, 1)
        return Image.fromarray(pixels.clip(0, 255).astype(np.uint8), "RGBA").filter(ImageFilter.GaussianBlur(0.55))


def smooth_noise(shape: tuple[int, int], cell: int, rng) -> np.ndarray:
    """Low-frequency noise in roughly [-1, 1]."""
    h, w = shape
    small = rng.normal(0, 1, (max(2, h // cell), max(2, w // cell))).astype(np.float32)
    return np.asarray(Image.fromarray(small, "F").resize((w, h), Image.BICUBIC)) / 1.5


def elastic(image: Image.Image, amplitude: float, cell: int, rng) -> Image.Image:
    pixels = np.asarray(image).astype(np.float32)
    h, w = pixels.shape[:2]
    dx = smooth_noise((h, w), cell, rng) * amplitude
    dy = smooth_noise((h, w), cell, rng) * amplitude
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return Image.fromarray(bilinear(pixels, xx + dx, yy + dy).clip(0, 255).astype(np.uint8), image.mode)


def bilinear(pixels: np.ndarray, sx: np.ndarray, sy: np.ndarray) -> np.ndarray:
    h, w = pixels.shape[:2]
    sx = np.clip(sx, 0, w - 1.001)
    sy = np.clip(sy, 0, h - 1.001)
    x0, y0 = sx.astype(int), sy.astype(int)
    fx, fy = (sx - x0)[..., None], (sy - y0)[..., None]
    top = pixels[y0, x0] * (1 - fx) + pixels[y0, x0 + 1] * fx
    bottom = pixels[y0 + 1, x0] * (1 - fx) + pixels[y0 + 1, x0 + 1] * fx
    return top * (1 - fy) + bottom * fy


def paper(size: tuple[int, int], rng, tone=(245, 241, 230)) -> np.ndarray:
    w, h = size
    page = np.ones((h, w, 3), np.float32) * np.array(tone, np.float32)
    page += smooth_noise((h, w), 150, rng)[..., None] * 5
    page += rng.normal(0, 2.5, (h, w, 1))
    fibers = Image.new("L", size, 0)
    draw = ImageDraw.Draw(fibers)
    for _ in range(w * h // 9000):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        angle = rng.uniform(0, np.pi)
        length = rng.uniform(4, 16)
        draw.line([(x, y), (x + np.cos(angle) * length, y + np.sin(angle) * length)], fill=int(rng.uniform(10, 30)), width=1)
    page -= np.asarray(fibers, np.float32)[..., None] * 0.35
    return page


def water_damage(page: np.ndarray, ink: np.ndarray, center: tuple[float, float], radius: float, rng) -> tuple[np.ndarray, np.ndarray]:
    """Tide-mark stain with slightly bled ink inside it."""
    h, w = page.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    wobble = smooth_noise((h, w), 70, rng) * radius * 0.25
    distance = np.hypot(xx - center[0], (yy - center[1]) * 1.3) + wobble
    inside = np.clip((radius - distance) / 25, 0, 1)
    ring = np.exp(-((distance - radius) / 7) ** 2)
    page = page * (1 - inside[..., None] * 0.05) - ring[..., None] * np.array([18, 24, 38], np.float32)
    bled = np.asarray(Image.fromarray(ink.astype(np.uint8), "RGBA").filter(ImageFilter.GaussianBlur(1.6)), np.float32)
    ink = ink * (1 - inside[..., None]) + bled * inside[..., None]
    return page, ink


def fold_line(page: np.ndarray, y: int) -> np.ndarray:
    h = page.shape[0]
    rows = np.arange(h, dtype=np.float32)[:, None, None]
    crease = np.exp(-((rows - y) / 2.2) ** 2) * 20 - np.exp(-((rows - y - 7) / 6) ** 2) * 6
    return page - crease


def perspective_coeffs(src, dst) -> list[float]:
    rows = []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    return np.linalg.solve(np.array(rows, np.float64), np.array(src, np.float64).reshape(8)).tolist()


def scan(
    form: Image.Image,
    ink: Image.Image,
    seed: int,
    angle: float = 0.8,
    fold_at: float | None = None,
    water: tuple[float, float, float] | None = None,
    margin: int = 46,
) -> Image.Image:
    """Combine a printed form and an ink layer into a realistic flatbed scan."""
    rng = np.random.default_rng(seed)
    w, h = form.size
    printed = np.asarray(form.convert("RGB"), np.float32)
    toner = 1 + rng.normal(0, 0.06, printed.shape[:2])[..., None] * (printed < 200)
    page = paper((w, h), rng) * (printed / 255.0) * toner
    ink_px = np.asarray(ink, np.float32)
    if water:
        page, ink_px = water_damage(page, ink_px, (water[0] * w, water[1] * h), water[2] * w, rng)
    alpha = ink_px[..., 3:4] / 255.0
    page = page * (1 - alpha) + ink_px[..., :3] * alpha * 0.92 + page * alpha * 0.08 * (ink_px[..., :3] / 255.0)
    if fold_at:
        page = fold_line(page, int(fold_at * h))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    light = 1.02 - 0.07 * (xx / w) - 0.04 * (yy / h) - 0.05 * (((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2))
    page = np.clip(page * light[..., None], 0, 255).astype(np.uint8)

    canvas = (w + 2 * margin, h + 2 * margin)
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    theta = np.radians(angle)
    cx, cy = canvas[0] / 2, canvas[1] / 2
    dst = []
    for x, y in src:
        x0, y0 = x - w / 2, y - h / 2
        dst.append((cx + x0 * np.cos(theta) - y0 * np.sin(theta) + rng.normal(0, 3),
                    cy + x0 * np.sin(theta) + y0 * np.cos(theta) + rng.normal(0, 3)))
    coeffs = perspective_coeffs(src, dst)
    scanned = Image.fromarray(page).transform(canvas, Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(233, 233, 231))
    mask = Image.new("L", (w, h), 255).transform(canvas, Image.PERSPECTIVE, coeffs, Image.BILINEAR, fillcolor=0)
    shadow = np.asarray(mask.filter(ImageFilter.GaussianBlur(5)), np.float32) / 255.0
    edge = np.clip(shadow - np.asarray(mask, np.float32) / 255.0, 0, 1)
    out = np.asarray(scanned, np.float32) * (1 - edge[..., None] * 0.55)
    out += rng.normal(0, 2.2, out.shape)
    return Image.fromarray(out.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.45))
