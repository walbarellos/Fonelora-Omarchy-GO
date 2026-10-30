#!/usr/bin/env python3
"""Template matching database engine for Fonelora-Omarchy-GO.
Maintains pre-cropped UI icon templates for sub-15ms normalized cross-correlation matching.
Replaces brittle heuristic color/pixel slicing with robust computer vision matching.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

TEMPLATES_DIR = Path(__file__).resolve().parent / "assets/templates"

# In-memory template cache
_TEMPLATE_CACHE: Dict[str, np.ndarray] = {}


def load_templates():
    """Pre-loads all template images into memory."""
    if not TEMPLATES_DIR.exists():
        return
    for fname in os.listdir(TEMPLATES_DIR):
        if fname.endswith(".png"):
            p = str(TEMPLATES_DIR / fname)
            img = cv2.imread(p)
            if img is not None:
                _TEMPLATE_CACHE[fname] = img


def match_template_in_roi(
    screen: np.ndarray,
    template_name: str,
    roi_bbox: Optional[Tuple[int, int, int, int]] = None,
    threshold: float = 0.82,
) -> Optional[Tuple[int, int, float]]:
    """Matches a template inside a screen image (optionally scoped to an ROI for <15ms speed).
    
    Args:
        screen: Full 1080x2460 BGR image.
        template_name: e.g. 'btn_catch_ok.png'.
        roi_bbox: (ymin, ymax, xmin, xmax). If None, searches full image.
        threshold: Minimum normalized correlation (0.0 to 1.0).

    Returns:
        (center_x, center_y, confidence) or None if no match above threshold.
    """
    if template_name not in _TEMPLATE_CACHE:
        p = str(TEMPLATES_DIR / template_name)
        if not os.path.exists(p):
            return None
        tmpl = cv2.imread(p)
        if tmpl is None:
            return None
        _TEMPLATE_CACHE[template_name] = tmpl

    tmpl = _TEMPLATE_CACHE[template_name]
    th, tw = tmpl.shape[:2]

    if roi_bbox is not None:
        ymin, ymax, xmin, xmax = roi_bbox
        roi = screen[ymin:ymax, xmin:xmax]
        offset_y, offset_x = ymin, xmin
    else:
        roi = screen
        offset_y, offset_x = 0, 0

    if roi.shape[0] < th or roi.shape[1] < tw:
        return None

    res = cv2.matchTemplate(roi, tmpl, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)

    if max_val >= threshold:
        cx = offset_x + max_loc[0] + tw // 2
        cy = offset_y + max_loc[1] + th // 2
        return cx, cy, float(max_val)

    return None


# Pre-load on import
load_templates()
