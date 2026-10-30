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

def is_main_menu_open(img: np.ndarray) -> bool:
    """Detects if the main Pokéball options menu (Pokédex, Batalhar, Loja, Pokémon) is open."""
    if img is None:
        return False
    # Check if close 'X' button is present at (540, 2300) with bright/white icon
    # and background is blurred/overlayed
    b, g, r = img[2300, 540]
    return (int(b) + int(g) + int(r)) > 600

def dismiss_popups(img: np.ndarray = None):
    """Dismiss common popups, open menus, dialogs, or banners to return to map."""
    if img is not None and is_main_menu_open(img):
        # Close main menu by tapping bottom X button
        adb_tap(540, 2300)
        time.sleep(1.0)
        return
    # Default bottom dismiss tap for level up, news, popups
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

def detect_glowing_boxes(img: np.ndarray):
    """Detects glowing mystery / treat / event boxes on the map."""
    if img is None:
        return []
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # Bright glowing orange/gold or sparkling items
    gold_mask = cv2.inRange(hsv, (12, 120, 140), (38, 255, 255))
    gold_mask[:900, :] = 0
    gold_mask[1900:, :] = 0
    # Exclude player avatar
    cv2.circle(gold_mask, (540, 1600), 120, 0, -1)
    
    cnts, _ = cv2.findContours(gold_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        a = cv2.contourArea(c)
        if 40 < a < 8000:
            x, y, w, h = cv2.boundingRect(c)
            boxes.append((x + w//2, y + h//2, a))
    boxes.sort(key=lambda b: (b[0]-540)**2 + (b[1]-1600)**2)
    return boxes

def extract_encounter_cp(img: np.ndarray) -> int:
    """Extracts CP of the Pokémon currently in the encounter screen."""
    if img is None:
        return 0
    try:
        import pytesseract
        # CP banner is at top center: y: 650..950, x: 250..850
        roi = img[650:950, 250:850]
        txt = pytesseract.image_to_string(roi).strip()
        # Look for 'PC' or 'CP' followed by digits
        import re
        m = re.search(r'(?:PC|CP)\s*([0-9]{2,5})', txt, re.IGNORECASE)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 0

def run_away_from_encounter():
    """Taps the flee / run away button at the top left (100, 180)."""
    adb_tap(100, 180)
    time.sleep(1.5)

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

def execute_curveball_throw():
    """Performs an authentic curveball flick to capture Pokémon."""
    adb_swipe(540, 2150, 540, 1250, 150)

def detect_pokestops(img: np.ndarray):
    """Detects nearby Pokéstops by blue or event-orange disk signature, strictly ignoring tall Gym towers."""
    if img is None:
        return []
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # Standard Blue Pokéstop disk:
    blue_mask = cv2.inRange(hsv, (95, 120, 100), (125, 255, 255))
    # Event / Halloween Orange Pokéstop disk:
    orange_mask = cv2.inRange(hsv, (5, 120, 100), (25, 255, 255))
    stop_mask = cv2.bitwise_or(blue_mask, orange_mask)

    stop_mask[:500, :] = 0
    stop_mask[2000:, :] = 0
    # Exclude player avatar
    cv2.circle(stop_mask, (540, 1600), 120, 0, -1)

    contours, _ = cv2.findContours(stop_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    stops = []
    for c in contours:
        area = cv2.contourArea(c)
        if 80 < area < 25000:
            x, y, w, h = cv2.boundingRect(c)
            # Filter out Gyms (Gym towers have large width/height or huge tall structures)
            if h > 130 and w > 140:
                continue
            stops.append((x + w//2, y + h//2, area))
    stops.sort(key=lambda s: (s[0]-540)**2 + (s[1]-1600)**2)
    return stops

def feed_berry_in_combat():
    """Feeds a Razz Berry (or current available berry) to the Pokémon before throwing."""
    # 1. Tap bottom-left Berry icon at (135, 2235)
    adb_tap(135, 2235)
    time.sleep(0.8)
    # 2. Tap the first berry in drawer (left slot at ~280, 2050)
    adb_tap(280, 2050)
    time.sleep(0.4)
    # 3. Flick/swipe berry toward Pokémon center (540, 2050 -> 540, 1400)
    adb_swipe(540, 2050, 540, 1400, 180)
    time.sleep(1.2)

def spin_and_collect_stop(x: int, y: int) -> bool:
    """Taps a pokestop, spins the photodisc ultra-fast (1.0~1.4s total), and closes it."""
    # Tap to open stop
    adb_tap(x, y)
    time.sleep(0.7)
    # Fast horizontal swipe across photodisc (1100 Y)
    adb_swipe(200, 1100, 880, 1100, 120)
    time.sleep(0.35)
    # Quick tap close 'X' button at bottom
    adb_tap(540, 2330)
    time.sleep(0.4)
    # In case of gym photodisc or popup, safety tap
    adb_tap(540, 2300)
    time.sleep(0.3)
    return True
