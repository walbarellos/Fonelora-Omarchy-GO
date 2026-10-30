#!/usr/bin/env python3
"""Vision and ADB automation driver for Fonelora-Omarchy-GO.
Interacts directly with Pokémon GO UI on Android:
- Map banner / popup dismissal
- Spawn detection and tapping
- Curveball Pokéball throws
- Pokéstop detection, spinning, and dismissal
- Inventory bag checks
"""
import subprocess
import time
import os
import random
import cv2
import numpy as np

DEVICE_SERIAL = os.environ.get("ANDROID_SERIAL", "adb-5A405WX00-aifnpK._adb-tls-connect._tcp")

def adb_cmd(*args):
    cmd = ["adb", "-s", DEVICE_SERIAL] + list(args)
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

def adb_tap(x: int, y: int, jitter=5):
    jx = int(x + random.uniform(-jitter, jitter))
    jy = int(y + random.uniform(-jitter, jitter))
    adb_cmd("shell", "input", "tap", str(jx), str(jy))
    time.sleep(random.uniform(0.1, 0.25))

def adb_swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 200):
    adb_cmd("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))
    time.sleep(random.uniform(0.15, 0.3))

def adb_screencap() -> np.ndarray:
    proc = subprocess.run(["adb", "-s", DEVICE_SERIAL, "exec-out", "screencap", "-p"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not proc.stdout:
        return None
    arr = np.frombuffer(proc.stdout, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)

def dismiss_popups():
    """Dismiss common popups, level ups, safety warnings or banners."""
    # Bottom dismiss button or OK buttons
    adb_tap(540, 2330)
    time.sleep(0.5)

def is_map_screen(img: np.ndarray) -> bool:
    """Checks if main map screen HUD is active (Pokeball menu at 540, 2300)."""
    if img is None:
        return False
    # Pokeball menu is at (540, 2300)
    b, g, r = img[2300, 540]
    # Check if close to [168, 170, 148] or non-dark
    return r > 100 and g > 100 and b > 100

def is_encounter_screen(img: np.ndarray) -> bool:
    """Checks if in Pokémon encounter screen."""
    if img is None:
        return False
    # In encounter, top left has flee icon and bottom center has Pokeball ready to throw
    # Pokeball at (540, 2150) is bright red/white
    b, g, r = img[2150, 540]
    return r > 120 and b < 60 and g < 60

def is_catch_success_screen(img: np.ndarray) -> bool:
    """Checks if 'POKEMON PEGO' or summary checkmark is visible."""
    if img is None:
        return False
    # Bottom center has green checkmark or OK button
    # Let's check text or bottom center color
    b, g, r = img[2300, 540]
    return (b, g, r) != (168, 170, 148)

def detect_spawns(img: np.ndarray):
    """Detects Pokémon spawns around player interaction radius."""
    if img is None:
        return []
    h, w, _ = img.shape
    # Focus on radius around player (540, 1600)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(mask, (540, 1600), 420, 255, -1)
    cv2.circle(mask, (540, 1600), 140, 0, -1) # exclude avatar

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    masked_edges = cv2.bitwise_and(edges, edges, mask=mask)

    contours, _ = cv2.findContours(masked_edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    spawns = []
    for c in contours:
        area = cv2.contourArea(c)
        if 80 < area < 25000:
            x, y, cw, ch = cv2.boundingRect(c)
            # Avoid bottom HUD buttons
            if y + ch > 2100 or y < 1100:
                continue
            spawns.append((x + cw//2, y + ch//2, area))
    
    # Sort closest to avatar
    spawns.sort(key=lambda s: (s[0]-540)**2 + (s[1]-1600)**2)
    return spawns

def detect_pokestops(img: np.ndarray):
    """Detects nearby Pokéstops by blue disk signature."""
    if img is None:
        return []
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    stop_mask = cv2.inRange(hsv, (95, 120, 120), (125, 255, 255))
    stop_mask[:500, :] = 0
    stop_mask[1800:, :] = 0
    contours, _ = cv2.findContours(stop_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    stops = []
    for c in contours:
        area = cv2.contourArea(c)
        if area > 100:
            x, y, w, h = cv2.boundingRect(c)
            stops.append((x + w//2, y + h//2, area))
    return stops

def execute_curveball_throw():
    """Performs an authentic curveball flick to capture Pokémon."""
    # Curve motion: start slightly left, spin, flick up to center
    adb_swipe(540, 2150, 540, 1250, 150)

def spin_and_collect_stop(x: int, y: int) -> bool:
    """Taps a pokestop, spins the photodisc, and closes it."""
    adb_tap(x, y)
    time.sleep(2.0)
    # Spin swipe
    adb_swipe(200, 1100, 880, 1100, 180)
    time.sleep(1.2)
    # Tap close button at (540, 2330)
    adb_tap(540, 2330)
    time.sleep(1.5)
    return True
