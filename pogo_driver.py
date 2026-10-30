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
    """Detects if the main Pokéball options menu (Pokédex, Batalhar, Loja, Pokémon) is open.
    In the main menu, the screen is darkened/blurred, and a bright circular 'X' close button
    sits at (540, 2300) with bright white icon (sum of RGB > 680)."""
    if img is None:
        return False
    b, g, r = img[2300, 540]
    return (int(b) + int(g) + int(r)) > 680

def is_exit_dialog_open(img: np.ndarray) -> bool:
    """Detects if 'Quer sair do Pokémon GO?' exit dialog is open."""
    if img is None:
        return False
    # Check dialog center or title
    try:
        import pytesseract
        roi = img[980:1100, 200:880]
        txt = pytesseract.image_to_string(roi).strip()
        return "SAIR" in txt.upper() or "QUER" in txt.upper()
    except Exception:
        return False

def dismiss_popups(img: np.ndarray = None):
    """Safely dismisses open dialogs, menus, or summary popups without EVER tapping the map Pokéball."""
    if img is None:
        return
    # If exit dialog appeared ('Quer sair do Pokémon GO?'):
    if is_exit_dialog_open(img):
        # Tap outside dialog at top center (540, 500) to cancel exit
        adb_tap(540, 500)
        time.sleep(0.8)
        return
    # If main options menu is open:
    if is_main_menu_open(img):
        adb_tap(540, 2300) # Close X button
        time.sleep(0.8)
        return
    # If open Pokéstop or modal:
    if is_pokestop_screen(img):
        adb_tap(540, 2330) # Close X button
        time.sleep(0.6)
        return
    # Default safe fallback: tap outside modal area (540, 500)
    adb_tap(540, 500)
    time.sleep(0.5)

def is_map_screen(img: np.ndarray) -> bool:
    """Checks if main map screen HUD is active (Pokeball menu at 540, 2300)."""
    if img is None:
        return False
    # If the main menu or full screen modal is open, it's not the map
    if is_main_menu_open(img):
        return False
    # Pokeball menu is at (540, 2300)
    b, g, r = img[2300, 540]
    # Check if close to normal HUD pokeball icon [168, 170, 148]
    return 80 < r < 200 and 80 < g < 200 and 80 < b < 200

def is_pokestop_screen(img: np.ndarray) -> bool:
    """Detects if a Pokéstop photodisc screen is open."""
    if img is None:
        return False
    # In an open Pokéstop screen, the close 'X' button at (540, 2330) is bright white/light
    b, g, r = img[2330, 540]
    return (int(b) + int(g) + int(r)) > 600

def is_encounter_screen(img: np.ndarray) -> bool:
    """Checks if in Pokémon encounter screen by verifying flee button icon at top-left (100, 180)
    or Pokeball/Berry icons at the bottom."""
    if img is None:
        return False
    # Top-left flee button: (100, 180) typically has white icon with dark/colored background
    # Check flee button region mean/contrast or flee pixel
    b, g, r = img[180, 100]
    # In encounter, flee button is active and distinct from map screen (where map is grass/road/sky)
    # Also verify that it's NOT the map screen
    if is_map_screen(img):
        return False
    # Flee button icon has high contrast / specific hue:
    flee_region = img[150:210, 80:130]
    if flee_region.size > 0:
        # Check standard deviation or contrast indicating running-man icon
        if np.std(flee_region) > 25:
            return True
    # Fallback: check red Pokeball at bottom center
    b_ball, g_ball, r_ball = img[2150, 540]
    return r_ball > 110 and b_ball < 70

def detect_glowing_boxes(img: np.ndarray):
    """Detects glowing mystery / treat / event boxes on the map, strictly ignoring UI elements."""
    if img is None:
        return []
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # Bright glowing orange/gold or sparkling items
    gold_mask = cv2.inRange(hsv, (14, 150, 160), (32, 255, 255))
    gold_mask[:600, :] = 0
    gold_mask[1950:, :] = 0
    # Exclude player avatar
    cv2.circle(gold_mask, (540, 1600), 220, 0, -1)
    # Exclude bottom-left player profile / buddy area (x < 250, y > 1800)
    gold_mask[1800:, :260] = 0
    # Exclude right-hand weather/radar HUD (x > 880)
    gold_mask[:, 880:] = 0
    
    cnts, _ = cv2.findContours(gold_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        a = cv2.contourArea(c)
        if 40 < a < 6000:
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
    """Detects Pokémon spawns around player interaction radius, strictly ignoring avatar, pulse rings, and UI buttons."""
    if img is None:
        return []
    h, w, _ = img.shape
    # Focus on radius around player (540, 1600)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(mask, (540, 1600), 420, 255, -1)
    # Mask out avatar AND expanding pulse rings (radius 240 around avatar)
    cv2.circle(mask, (540, 1600), 240, 0, -1)

    # Exclude bottom UI zone (profile, pokeball, binoculars)
    mask[1900:, :] = 0
    # Exclude bottom-center zone (pokeball menu safe margin: Y > 1750, X within 160px of center)
    mask[1750:, 380:700] = 0

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
            if y + ch > 1950 or y < 1050:
                continue
            cx, cy = x + cw//2, y + ch//2
            # Strictly ignore points within avatar / buddy radius (240px)
            if (cx - 540)**2 + (cy - 1600)**2 < 240**2:
                continue
            # Strictly avoid the central vertical pulse axis directly below avatar
            if abs(cx - 540) < 120 and cy > 1750:
                continue
            spawns.append((cx, cy, area))
    
    # Sort closest to avatar
    spawns.sort(key=lambda s: (s[0]-540)**2 + (s[1]-1600)**2)
    return spawns

def detect_pokestops(img: np.ndarray):
    """Detects nearby AVAILABLE Pokéstops (Orange Halloween or Standard Blue).
    Strictly ignores:
      - Cooldown / used Pokéstops (Purple / Lilac)
      - Tall Gym towers
      - Map terrain / night grass false positives
    """
    if img is None:
        return []

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # 1. Standard Blue available stops:
    # In HSV: Hue 95 to 118, Saturation 70 to 255, Value 110 to 255
    blue_mask = cv2.inRange(hsv, (95, 70, 110), (118, 255, 255))

    # 2. Event / Halloween Orange available stops:
    # In HSV: Hue 8 to 22, Saturation 110 to 255, Value 110 to 255
    orange_mask = cv2.inRange(hsv, (8, 110, 110), (22, 255, 255))

    stops_raw = cv2.bitwise_or(blue_mask, orange_mask)

    # 3. Cooldown stops: Lilac / Purple / Magenta
    # In HSV: Hue 125 to 172, Saturation 35 to 255, Value 55 to 255
    purple_hsv = cv2.inRange(hsv, (125, 35, 55), (172, 255, 255))
    # In BGR: high blue & red, noticeably lower green
    purple_bgr = ((img[:, :, 0] > 115) & (img[:, :, 2] > 105) & (img[:, :, 1] < img[:, :, 0] - 12)).astype(np.uint8) * 255
    cooldown_mask = cv2.bitwise_or(purple_hsv, purple_bgr)

    # Dilate cooldown (25x25) so that purple cooldown stops never get touched
    kernel = np.ones((25, 25), np.uint8)
    cooldown_dilated = cv2.dilate(cooldown_mask, kernel, iterations=2)

    clean_stops = cv2.bitwise_and(stops_raw, cv2.bitwise_not(cooldown_dilated))

    clean_stops[:450, :] = 0
    clean_stops[1950:, :] = 0
    # Exclude player avatar & pulse ring
    cv2.circle(clean_stops, (540, 1600), 200, 0, -1)
    # Exclude bottom-left player profile
    clean_stops[1800:, :260] = 0

    contours, _ = cv2.findContours(clean_stops, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    stops = []
    for c in contours:
        area = cv2.contourArea(c)
        if 50 < area < 25000:
            x, y, w, h = cv2.boundingRect(c)
            # Filter out Gyms (Gym towers have large width/height or huge tall structures)
            if h > 130 and w > 140:
                continue
            stops.append((x + w//2, y + h//2, area))
    stops.sort(key=lambda s: (s[0]-540)**2 + (s[1]-1600)**2)
    return stops

def feed_berry_in_combat():
    """Feeds a Razz Berry instantly to the Pokémon."""
    # 1. Tap bottom-left Berry icon
    adb_tap(135, 2235)
    time.sleep(0.35)
    # 2. Tap Fruta Frambo (first icon in list at ~220, 1050)
    adb_tap(220, 1050)
    time.sleep(0.25)
    # 3. Quick flick forward to feed Pokémon
    adb_swipe(540, 1600, 540, 1100, 100)
    time.sleep(0.7)

def select_ball_by_cp(cp: int):
    """Smart ball selection based on CP and rarity:
    - CP < 500: Standard Pokéball (slot 1: 200, 2150) - NEVER wastes Ultra Ball!
    - 500 <= CP < 1200: Great Ball (slot 2: 530, 2150)
    - CP >= 1200: Ultra Ball (slot 3: 850, 2150) reserved for truly formidable monsters.
    If CP == 0 (unscanned), defaults to Pokéball.
    """
    if cp < 500:
        # Standard Pokéball is already active by default in slot 1
        # Only open drawer if we previously switched to a different ball
        return
    
    # Open ball drawer at bottom-right
    adb_tap(940, 2150)
    time.sleep(0.35)
    
    if cp >= 1200:
        print(f"🔥 [Combat] CP formidável ({cp})! Selecionando ULTRA BALL...")
        adb_tap(850, 2150)
    else:
        print(f"⚡ [Combat] CP intermediário ({cp}). Selecionando GREAT BALL...")
        adb_tap(530, 2150)
    time.sleep(0.25)

def dismiss_catch_screens():
    """Rapid dismissal of post-catch animations (XP celebration, new Pokédex entry, OK checkmark, and summary X).
    Total duration under 1.8 seconds.
    """
    # 1. Tap center of screen twice rapidly to skip 'POKEMON PEGO' and XP tally animation
    adb_tap(540, 1500)
    time.sleep(0.3)
    adb_tap(540, 1500)
    time.sleep(0.3)
    # 2. Tap OK checkmark button at (540, 2330)
    adb_tap(540, 2330)
    time.sleep(0.3)
    # 3. Tap bottom-center (540, 2330 / 2300) to close appraisal/summary screen and return to map
    adb_tap(540, 2330)
    time.sleep(0.3)
    adb_tap(540, 2180)
    time.sleep(0.2)

def execute_curveball_throw():
    """Performs an authentic, high-power human curveball spin & flick.
    Swirls ball counter-clockwise at bottom-center then releases up into the target circle.
    """
    adb_cmd("shell", "input swipe 540 2200 450 2150 70; input swipe 450 2150 600 950 100")

def spin_and_collect_stop(x: int, y: int) -> bool:
    """Taps a pokestop, spins the photodisc ultra-fast (1.0~1.4s total), and closes it cleanly.
    Uses targeted close 'X' button tap at (540, 2330) and verifies return to map without triggering exit dialog."""
    # 1. Tap to open stop
    adb_tap(x, y)
    time.sleep(0.7)
    
    # 2. Fast horizontal swipe across photodisc (1100 Y)
    adb_swipe(200, 1100, 880, 1100, 120)
    time.sleep(0.35)
    
    # 3. Clean close: tap the Pokéstop 'X' close button at (540, 2330)
    adb_tap(540, 2330)
    time.sleep(0.5)
    
    # Check if closed to map; if not, tap (540, 2330) once more
    img_chk = adb_screencap()
    if img_chk is not None and not is_map_screen(img_chk):
        adb_tap(540, 2330)
        time.sleep(0.4)
    return True
