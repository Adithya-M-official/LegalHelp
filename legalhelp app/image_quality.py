"""
image_quality.py

Lightweight, dependency-free (beyond Pillow) heuristics for catching
common image-quality problems -- blur, glare/overexposure, and
too-low resolution -- *before* an image is sent to Gemini.

These are deliberately simple, fixed-threshold heuristics rather than
a full computer-vision pipeline. They are meant to catch the obvious,
common cases called out in the README's Limitations section ("poor
image quality (blur, glare, handwriting) can affect output quality")
so users get fast, actionable feedback instead of a confusing or
low-quality answer later.

All processing happens in memory (Pillow `Image` objects); nothing is
written to disk, consistent with the rest of the app's privacy design.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Tunable constants
# --------------------------------------------------------------------------
# These are fixed, documented heuristic thresholds rather than values
# tuned against a labeled dataset. They are intentionally conservative
# (biased toward warning rather than blocking) since a false "looks
# fine" is cheaper for the user than being blocked from a usable photo.

# Below this many total pixels (width * height), an image is considered
# too low-resolution for reliable document reading.
MIN_TOTAL_PIXELS = 400 * 400

# Laplacian-variance-style sharpness score. Computed via a Pillow edge
# filter rather than a true Laplacian convolution (to avoid adding
# numpy/scipy as a dependency). Below this, an image is flagged as
# likely blurry. This is a relative, unitless score -- the threshold
# was chosen conservatively (low) to catch clearly, heavily out-of-focus
# photos while tolerating normal phone-camera softness and texture;
# scores for genuinely sharp document photos with visible text typically
# run in the thousands, while heavily blurred images stay in the low
# hundreds or less.
BLUR_VARIANCE_THRESHOLD = 300.0

# Fraction of pixels (0.0-1.0) that must be near-white (glare/blown
# highlight) before an image is flagged for glare.
GLARE_BRIGHT_PIXEL_RATIO = 0.15

# A pixel (in grayscale 0-255) at or above this value counts as
# "near-white" for glare-detection purposes.
GLARE_BRIGHTNESS_CUTOFF = 245

# Fraction of pixels that must be near-black before an image is
# flagged as likely too dark / underexposed.
DARK_PIXEL_RATIO = 0.6
DARK_BRIGHTNESS_CUTOFF = 25

# Images are downscaled to this max dimension before analysis purely
# for speed -- quality heuristics don't need full resolution.
ANALYSIS_MAX_DIMENSION = 800


@dataclass
class ImageQualityReport:
    """Result of running quality heuristics against an uploaded image."""

    is_low_resolution: bool = False
    is_likely_blurry: bool = False
    has_glare: bool = False
    is_too_dark: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


def _downscale_for_analysis(image: Image.Image) -> Image.Image:
    """Return a grayscale, downscaled copy of `image` for fast analysis."""
    working = image.convert("L")
    width, height = working.size
    largest_dimension = max(width, height)
    if largest_dimension > ANALYSIS_MAX_DIMENSION:
        scale = ANALYSIS_MAX_DIMENSION / largest_dimension
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        working = working.resize(new_size, Image.BILINEAR)
    return working


def _estimate_sharpness(grayscale_image: Image.Image) -> float:
    """
    Estimate sharpness using the variance of an edge-filtered image.

    A true "variance of Laplacian" blur metric normally requires
    numpy/OpenCV. Here we approximate it with Pillow's built-in
    FIND_EDGES kernel (a discrete Laplacian-like convolution) and
    compute the variance of the resulting pixel histogram by hand,
    avoiding any new dependency.
    """
    edges = grayscale_image.filter(ImageFilter.FIND_EDGES)
    histogram = edges.histogram()
    total_pixels = sum(histogram)
    if total_pixels == 0:
        return 0.0

    mean = sum(value * count for value, count in enumerate(histogram)) / total_pixels
    variance = sum(
        count * ((value - mean) ** 2) for value, count in enumerate(histogram)
    ) / total_pixels
    return variance


def _bright_pixel_ratio(grayscale_image: Image.Image, cutoff: int) -> float:
    """Fraction of pixels at or above `cutoff` brightness."""
    histogram = grayscale_image.histogram()
    total_pixels = sum(histogram)
    if total_pixels == 0:
        return 0.0
    bright_pixels = sum(histogram[cutoff:])
    return bright_pixels / total_pixels


def _dark_pixel_ratio(grayscale_image: Image.Image, cutoff: int) -> float:
    """Fraction of pixels at or below `cutoff` brightness."""
    histogram = grayscale_image.histogram()
    total_pixels = sum(histogram)
    if total_pixels == 0:
        return 0.0
    dark_pixels = sum(histogram[: cutoff + 1])
    return dark_pixels / total_pixels


def assess_image_quality(image: Image.Image) -> ImageQualityReport:
    """
    Run all quality heuristics against an uploaded document image.

    Args:
        image: A Pillow Image, already opened/verified by the caller.

    Returns:
        ImageQualityReport: Flags and human-readable warnings for any
        detected issues. An image can trigger multiple warnings at
        once (e.g. both dark and blurry).
    """
    report = ImageQualityReport()

    try:
        width, height = image.size
        if width * height < MIN_TOTAL_PIXELS:
            report.is_low_resolution = True
            report.warnings.append(
                "This image is quite low-resolution, which may make small "
                "text hard to read accurately."
            )

        grayscale = _downscale_for_analysis(image)

        sharpness = _estimate_sharpness(grayscale)
        if sharpness < BLUR_VARIANCE_THRESHOLD:
            report.is_likely_blurry = True
            report.warnings.append(
                "This image looks like it might be blurry or out of focus."
            )

        glare_ratio = _bright_pixel_ratio(grayscale, GLARE_BRIGHTNESS_CUTOFF)
        if glare_ratio >= GLARE_BRIGHT_PIXEL_RATIO:
            report.has_glare = True
            report.warnings.append(
                "This image appears to have glare or a bright reflection "
                "covering part of the document."
            )

        dark_ratio = _dark_pixel_ratio(grayscale, DARK_BRIGHTNESS_CUTOFF)
        if dark_ratio >= DARK_PIXEL_RATIO:
            report.is_too_dark = True
            report.warnings.append(
                "This image looks quite dark, which may make text hard to read."
            )

    except Exception:  # noqa: BLE001 - quality checks must never crash the app
        logger.exception("Image quality assessment failed; skipping checks.")
        # Return whatever was accumulated so far (likely an empty,
        # warning-free report) rather than blocking the user.

    return report
