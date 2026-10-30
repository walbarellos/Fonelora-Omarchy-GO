#!/usr/bin/env python3
"""Vision and high-speed ADB automation driver for Fonelora-Omarchy-GO.
Interacts directly with Pokémon GO UI on Android (1080x2460):
- Fast raw gzip screencap (~1.3s over wireless TLS ADB vs 5-10s PNG)
- 4-way verified screen state classifiers (Map, Encounter, Catch OK, Summary/Stop Close)
- Single continuous Pokéball throw (zero finger drop)
- Smart CP-based ball selection + Razz Berry feeding
- Halloween Orange & Standard Blue Pokéstop detection with dilated Purple cooldown masking
- HSV terrain-subtracted wild Pokémon spawn & glowing box detection
"""
from __future__ import annotations

import os
import random
import re
import struct
import subprocess
import time
import zlib
from typing import List, Optional, Tuple

import cv2
import numpy as np

DEVICE_SERIAL = os.environ.get("ANDROID_SERIAL", "adb-5A405WX00-aifnpK._adb-tls-connect._tcp")

# Track active ball slot so we don't needlessly open the ball drawer for CP < 500
_CURRENT_BALL_SLOT = 1  # 1 = Pokéball, 2 = Great Ball, 3 = Ultra Ball


def adb_cmd(*args, timeout: float = 10.0):
    cmd = ["adb", "-s", DEVICE_SERIAL] + list(args)
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


def adb_shell(script: str, timeout: float = 10.0):
    """Executes one or more shell commands in a single ADB round-trip."""
    return adb_cmd("shell", script, timeout=timeout)


def adb_tap(x: int, y: int, jitter: int = 3, delay: float = 0.05):
    jx = int(x + random.uniform(-jitter, jitter))
    jy = int(y + random.uniform(-jitter, jitter))
    adb_cmd("shell", "input", "tap", str(jx), str(jy))
    if delay > 0:
        time.sleep(delay)


def adb_swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 150, delay: float = 0.05):
    adb_cmd("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))
    if delay > 0:
        time.sleep(delay)


def adb_screencap() -> Optional[np.ndarray]:
    """Captures 1080x2460 screen via fast raw gzip stream (~1.3s over wireless ADB),
    with automatic fallback to PNG screencap if needed."""
    try:
        proc = subprocess.run(
            ["adb", "-s", DEVICE_SERIAL, "exec-out", "screencap | gzip -1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8.0,
        )
        if proc.returncode == 0 and len(proc.stdout) > 64:
            raw = zlib.decompress(proc.stdout, 16 + zlib.MAX_WBITS)
            if len(raw) > 24:
                w, h, _fmt = struct.unpack_from("<III", raw, 0)
                expected = w * h * 4
                hdr = len(raw) - expected
                if 400 <= w <= 3000 and 800 <= h <= 5000 and hdr in (12, 16, 20):
                    rgba = np.frombuffer(raw, dtype=np.uint8, offset=hdr, count=expected).reshape((h, w, 4))
                    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
    except Exception:
        pass

    # Fallback to standard PNG screencap
    try:
        proc = subprocess.run(
            ["adb", "-s", DEVICE_SERIAL, "exec-out", "screencap", "-p"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=12.0,
        )
        if proc.returncode == 0 and proc.stdout:
            arr = np.frombuffer(proc.stdout, dtype=np.uint8)
            return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Verified Screen State Classifiers
# ---------------------------------------------------------------------------

def is_map_screen(img: np.ndarray) -> bool:
    """20x20 patch Red-Top + White-Bottom signature check on the map HUD Pokéball,
    100% immune to single-pixel walking bounce or pulse animations."""
    if img is None or img.shape[0] < 2400:
        return False
    top_patch = img[2255:2275, 530:550]
    bot_patch = img[2340:2360, 530:550]
    top_red = ((top_patch[:, :, 2] > 190) & (top_patch[:, :, 0] < 120) & (top_patch[:, :, 1] < 110)).mean() > 0.50
    bot_wht = (bot_patch.min(axis=2) > 205).mean() > 0.50
    return bool(top_red and bot_wht)


def is_main_menu_open(img: np.ndarray) -> bool:
    """Detects if the main Pokéball options menu (Pokédex, Batalhar, Loja, Pokémon, Itens) is open
    by verifying the 3 white circular menu buttons AND excluding solid-white summary cards."""
    if img is None or img.shape[0] < 2400 or is_map_screen(img):
        return False
    mid_not_card = img[1250:1400, 350:700].min(axis=2).mean() < 225
    if not mid_not_card:
        return False
    c_pokedex = (img[1560:1640, 195:275].min(axis=2) > 210).mean()
    c_batalhar = (img[1560:1640, 725:805].min(axis=2) > 210).mean()
    c_loja = (img[1775:1855, 460:540].min(axis=2) > 210).mean()
    return bool(c_pokedex > 0.40 and c_batalhar > 0.40 and c_loja > 0.40)


def is_encounter_screen(img: np.ndarray) -> bool:
    """Detects active wild Pokémon combat screen using flee icon + bottom berry/ball drawers,
    distinguishing 100% from open Pokéstops and summary screens."""
    if img is None or img.shape[0] < 2400 or is_map_screen(img):
        return False
    flee_white = (img[140:215, 65:140].min(axis=2) > 220).mean()
    berry_btn = img[2200:2270, 100:170].mean()
    ball_btn = img[2200:2270, 910:980].mean()
    gap_l = int(img[2330, 280].max())
    gap_r = int(img[2330, 800].max())
    return (
        flee_white > 0.035
        and berry_btn > 105
        and ball_btn > 105
        and gap_l < 155
        and gap_r < 155
    )


def is_item_drawer_open(img: np.ndarray) -> bool:
    """Detects if the bottom combat item sheet ('FRUTAS' or 'POKÉ BOLAS') is open."""
    if img is None or img.shape[0] < 2400 or is_map_screen(img):
        return False
    tray_corner = img[2015:2075, 60:320]
    above_tray = img[1860:1940, 60:300]
    return bool(tray_corner.mean() > 200 and tray_corner.std() < 10 and above_tray.mean() < 45)


def has_close_or_check_button(img: np.ndarray) -> bool:
    """Detects either:
    - The Dark Teal circular checkmark (✓) / (X) button on Pokémon Summary / Passe GO at (540, 2320)
    - The Bright White circular close (X) button on Pokéstop / Bag / Modal screens at (540, 2325)
    Strictly excludes the full-width grey combat item drawer ('FRUTAS' / 'POKÉ BOLAS').
    """
    if img is None or img.shape[0] < 2400 or is_map_screen(img) or is_encounter_screen(img):
        return False
    if is_item_drawer_open(img):
        return False
    roi = img[2275:2365, 495:585]
    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    teal_check = (cv2.inRange(hsv_roi, (82, 100, 75), (108, 255, 230)) > 0).mean() > 0.22
    white_close = (roi.min(axis=2) > 200).mean() > 0.25 and int(img[2320, 300].min()) < 190
    return bool(teal_check or white_close)


def has_catch_ok_button(img: np.ndarray) -> bool:
    """Detects the 'POKÉMON PEGO' XP/Stardust reward card with green 'OK' button at (540, 1544).
    Excludes Pokémon Summary screens (which have the teal ✓ button at 540, 2320)."""
    if img is None or img.shape[0] < 2400 or is_map_screen(img):
        return False
    if has_close_or_check_button(img) or is_item_drawer_open(img):
        return False
    if int(img[1350, 300].min()) <= 215:
        return False
    hsv_btn = cv2.cvtColor(img[1490:1600, 350:730], cv2.COLOR_BGR2HSV)
    green_ratio = (cv2.inRange(hsv_btn, (45, 55, 145), (95, 255, 255)) > 0).mean()
    return bool(green_ratio > 0.40)


def is_pokestop_screen(img: np.ndarray) -> bool:
    """Detects if a Pokéstop photodisc screen is open."""
    if img is None or img.shape[0] < 2400 or is_map_screen(img) or is_encounter_screen(img):
        return False
    roi = img[2285:2365, 500:580]
    return bool((roi.min(axis=2) > 200).mean() > 0.25)


def is_exit_dialog_open(img: np.ndarray) -> bool:
    """Detects if 'Quer sair do Pokémon GO?' exit confirmation dialog is open."""
    if img is None:
        return False
    try:
        # Quick check: white modal box in center before invoking OCR
        if int(img[1050, 540].min()) < 210:
            return False
        import pytesseract
        roi = img[960:1120, 200:880]
        txt = pytesseract.image_to_string(roi).strip().upper()
        return "SAIR" in txt or "QUER" in txt
    except Exception:
        return False


_UNKNOWN_FRAME_STREAK = 0


def dismiss_popups(img: Optional[np.ndarray] = None) -> str:
    """Safely dismisses non-map screens ONE step at a time with full 1.15s transition settle
    after any (540, 23xx) close tap, making it impossible to double-tap into the map Pokéball menu."""
    global _UNKNOWN_FRAME_STREAK

    if img is None or is_map_screen(img):
        _UNKNOWN_FRAME_STREAK = 0
        return "map"

    if is_item_drawer_open(img):
        _UNKNOWN_FRAME_STREAK = 0
        print("⚡ [UI] Bandeja de Frutas/Bolas aberta -> fechando em (540, 1400)...")
        adb_tap(540, 1400, jitter=3, delay=0.55)
        return "item_drawer"

    if is_main_menu_open(img):
        _UNKNOWN_FRAME_STREAK = 0
        print("⚡ [UI] Menu principal aberto -> fechando em (540, 2300) e aguardando retorno ao mapa...")
        adb_tap(540, 2300, jitter=2, delay=1.15)
        return "main_menu"

    if has_catch_ok_button(img):
        _UNKNOWN_FRAME_STREAK = 0
        print("⚡ [UI] Card 'POKÉMON PEGO' -> clicando OK em (540, 1544)...")
        adb_tap(540, 1544, jitter=3, delay=1.00)
        return "catch_ok"

    if has_close_or_check_button(img):
        _UNKNOWN_FRAME_STREAK = 0
        print("⚡ [UI] Tela de Resumo (✓) ou Modal (X) -> fechando em (540, 2315) e aguardando mapa...")
        adb_tap(540, 2315, jitter=2, delay=1.15)
        return "close_or_check"

    if is_exit_dialog_open(img):
        _UNKNOWN_FRAME_STREAK = 0
        print("⚡ [UI] Diálogo de saída detectado -> cancelando fora do modal (540, 450)...")
        adb_tap(540, 450, jitter=3, delay=0.80)
        return "exit_dialog"

    # Transitional animation frame (fade-in/out): wait once before tapping anything!
    _UNKNOWN_FRAME_STREAK += 1
    if _UNKNOWN_FRAME_STREAK == 1:
        time.sleep(0.65)
        return "waiting_transition"

    # Only if stuck on a true unknown popup/banner for 2+ frames, tap safe top sky (540, 420)
    print("⚡ [UI] Popup desconhecido persistente -> toque seguro no topo (540, 420)...")
    adb_tap(540, 420, jitter=3, delay=0.70)
    return "fallback"


# ---------------------------------------------------------------------------
# Map Object Detectors (Pokéstops, Spawns, Glowing Boxes)
# ---------------------------------------------------------------------------

def detect_pokestops(img: np.ndarray) -> List[Tuple[int, int, int]]:
    """Detects nearby AVAILABLE Pokéstops (Neon Orange Halloween or Neon Cyan-Blue).
    Strictly masks out Purple/Lilac cooldown stops PLUS a 220x160 region around/below them
    so the orange Halloween pumpkin base under a purple stop is NEVER mistaken for an available stop.
    """
    if img is None:
        return []

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # 1. Neon Orange Halloween active stops (avoids dull brown/grey buildings)
    orange_mask = cv2.inRange(hsv, (10, 210, 210), (22, 255, 255))

    # 2. Standard Neon Cyan-Blue active stops (high Sat & Val avoids night roads/roofs)
    blue_mask = cv2.inRange(hsv, (96, 185, 200), (114, 255, 255))

    stops_raw = cv2.bitwise_or(orange_mask, blue_mask)

    # 3. Cooldown Purple / Lilac / Magenta stops:
    # Dilate generously (220x160) so the orange Halloween pumpkins at the stop's base are masked out!
    purple_mask = cv2.inRange(hsv, (132, 65, 165), (172, 255, 255))
    kernel_purple = np.ones((220, 160), np.uint8)
    purple_dilated = cv2.dilate(purple_mask, kernel_purple, iterations=1)

    clean_stops = cv2.bitwise_and(stops_raw, cv2.bitwise_not(purple_dilated))

    # Restrict to interactive map playfield (avatar at ~505, 1585)
    clean_stops[:1150, :] = 0
    clean_stops[1940:, :] = 0
    cv2.circle(clean_stops, (505, 1585), 95, 0, -1)
    # Exclude bottom-left trainer/buddy portrait & right-side HUD icons
    clean_stops[1800:, :270] = 0
    clean_stops[:, 890:] = 0
    # Exclude out-of-range white-ring stops on far left edge
    clean_stops[:, :140] = 0

    contours, _ = cv2.findContours(clean_stops, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    stops: List[Tuple[int, int, int]] = []
    for c in contours:
        area = cv2.contourArea(c)
        if 800 < area < 35000:
            x, y, w, h = cv2.boundingRect(c)
            # Filter out huge Gym towers
            if h > 220 and w > 220:
                continue
            stops.append((x + w // 2, y + h // 2, int(area)))

    stops.sort(key=lambda s: (s[0] - 505) ** 2 + (s[1] - 1585) ** 2)
    return stops


def detect_spawns(img: np.ndarray) -> List[Tuple[int, int, int]]:
    """Detects wild Pokémon spawns around the player using HSV terrain & UI subtraction,
    avoiding night road/roof Canny edge false positives, avatar, pink ring, and Buddy Gengar."""
    if img is None:
        return []

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, w, _ = img.shape

    roi_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(roi_mask, (505, 1585), 390, 255, -1)
    cv2.circle(roi_mask, (505, 1585), 105, 0, -1)
    roi_mask[:1180, :] = 0
    roi_mask[1910:, :] = 0
    roi_mask[1800:, :270] = 0
    roi_mask[:, 880:] = 0
    roi_mask[:, :205] = 0  # avoid left-edge out-of-range pokestop rings

    # Map roads, grass, and building roofs all lie in Hue 82..118, Val 45..195
    terrain = cv2.inRange(hsv, (82, 18, 45), (118, 255, 195))

    # Pink interaction ring + purple cooldown stops + purple Buddy Gengar
    purple_pink = cv2.inRange(hsv, (120, 35, 40), (174, 255, 255))
    big_purple = np.zeros((h, w), dtype=np.uint8)
    pcnts, _ = cv2.findContours(purple_pink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in pcnts:
        area = cv2.contourArea(c)
        if area > 900:
            x, y, cw, ch = cv2.boundingRect(c)
            fill = area / float(max(1, cw * ch))
            # Solid purple bodies (Gengar buddy, cooldown Pokéstop) have high fill ratio;
            # the thin pink interaction ring has fill < 0.12 so it is NOT dilated into a giant donut!
            if fill > 0.20:
                cv2.drawContours(big_purple, [c], -1, 255, -1)
    big_purple = cv2.dilate(big_purple, np.ones((95, 95), np.uint8), iterations=1)

    # Mask out active orange/blue Pokéstops & their glowing pumpkin bases
    orange_stops = cv2.inRange(hsv, (8, 175, 175), (24, 255, 255))
    blue_stops = cv2.inRange(hsv, (96, 185, 200), (114, 255, 255))
    stops_big = cv2.dilate(cv2.bitwise_or(orange_stops, blue_stops), np.ones((85, 85), np.uint8), iterations=1)

    exclude = terrain | cv2.dilate(purple_pink, np.ones((5, 5), np.uint8)) | big_purple | stops_big
    fg = cv2.bitwise_and(roi_mask, cv2.bitwise_not(exclude))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))

    cnts, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    spawns: List[Tuple[int, int, int]] = []
    for c in cnts:
        area = cv2.contourArea(c)
        if 380 < area < 18000:
            x, y, cw, ch = cv2.boundingRect(c)
            cx, cy = x + cw // 2, y + ch // 2
            spawns.append((cx, cy, int(area)))

    spawns.sort(key=lambda s: (s[0] - 505) ** 2 + (s[1] - 1585) ** 2)
    return spawns


def detect_glowing_boxes(img: np.ndarray) -> List[Tuple[int, int, int]]:
    """Detects glowing gold/mystery boxes on the map while excluding Pokéstops and HUD icons."""
    if img is None:
        return []
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gold_mask = cv2.inRange(hsv, (18, 120, 180), (35, 255, 255))

    # Subtract Pokéstops so pumpkin glow is never mistaken for a box
    orange_stops = cv2.inRange(hsv, (8, 195, 195), (23, 255, 255))
    stops_dil = cv2.dilate(orange_stops, np.ones((90, 90), np.uint8), iterations=1)
    gold_mask = cv2.bitwise_and(gold_mask, cv2.bitwise_not(stops_dil))

    gold_mask[:1150, :] = 0
    gold_mask[1920:, :] = 0
    cv2.circle(gold_mask, (505, 1585), 105, 0, -1)
    gold_mask[1800:, :270] = 0
    gold_mask[:, 880:] = 0

    cnts, _ = cv2.findContours(gold_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: List[Tuple[int, int, int]] = []
    for c in cnts:
        area = cv2.contourArea(c)
        if 80 < area < 2500:
            x, y, w, h = cv2.boundingRect(c)
            boxes.append((x + w // 2, y + h // 2, int(area)))
    boxes.sort(key=lambda b: (b[0] - 505) ** 2 + (b[1] - 1585) ** 2)
    return boxes


# ---------------------------------------------------------------------------
# Combat & Pokéstop Actions
# ---------------------------------------------------------------------------

def extract_encounter_cp(img: np.ndarray) -> int:
    """Fast (~140ms) CP extraction across ground and flying Pokémon heights (Y=200..960)."""
    if img is None:
        return 0
    try:
        import pytesseract
        roi = img[200:960, 240:840]
        small = cv2.resize(roi, (0, 0), fx=0.65, fy=0.65, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        _, bw = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY_INV)
        txt = pytesseract.image_to_string(bw, config="--psm 6").strip()
        m = re.search(r"(?:PC|CP)\s*([0-9]{2,5})", txt, re.IGNORECASE)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 0


def run_away_from_encounter():
    """Taps the flee button at top-left (102, 178)."""
    adb_tap(102, 178, jitter=3, delay=0.9)


def feed_berry_in_combat():
    """Feeds a Razz Berry (Fruta Frambo) reliably when encounter is hard (CP >= 550 or breakout):
    1. Open berry drawer at (135, 2235) and wait 0.65s for drawer slide-up animation
    2. Select slot 1 berry at (200, 2180) and wait 0.45s
    3. Tap active berry at (520, 2180) to toss it, then wait 1.1s for Pokéball to reappear."""
    adb_shell(
        "input tap 135 2235; sleep 0.65; "
        "input tap 200 2180; sleep 0.45; "
        "input tap 520 2180"
    )
    time.sleep(1.10)


def select_ball_by_cp(cp: int):
    """Smart ball selection based on CP:
    - CP < 550: Standard Pokéball (slot 1: 200, 2180) — saves Ultra Balls & zero delay!
    - 550 <= CP < 1200: Great Ball (slot 2: 535, 2180)
    - CP >= 1200: Ultra Ball (slot 3: 865, 2180)
    """
    global _CURRENT_BALL_SLOT

    if cp < 550:
        if _CURRENT_BALL_SLOT != 1:
            print(f"⚪ [Combat] CP normal ({cp}). Voltando para Pokébola comum...")
            adb_shell("input tap 945 2235; sleep 0.65; input tap 200 2180")
            _CURRENT_BALL_SLOT = 1
            time.sleep(0.40)
        return

    if cp >= 1200:
        if _CURRENT_BALL_SLOT != 3:
            print(f"🔥 [Combat] CP formidável ({cp})! Selecionando ULTRA BALL...")
            adb_shell("input tap 945 2235; sleep 0.65; input tap 865 2180")
            _CURRENT_BALL_SLOT = 3
            time.sleep(0.40)
    else:
        if _CURRENT_BALL_SLOT != 2:
            print(f"⚡ [Combat] CP intermediário ({cp}). Selecionando GREAT BALL...")
            adb_shell("input tap 945 2235; sleep 0.65; input tap 535 2180")
            _CURRENT_BALL_SLOT = 2
            time.sleep(0.40)


def execute_curveball_throw(attempt: int = 1):
    """Executes a single uninterrupted high-velocity throw starting directly on the Pokéball
    center (540, 2230) up into the target ring (~1000-1035 Y) in 135ms.
    Never chains two swipes (which previously caused ACTION_UP and dropped the ball!)."""
    target_y = 1020 if attempt == 1 else (990 if attempt == 2 else 1045)
    target_x = 540 + int(random.uniform(-12, 12))
    adb_shell(f"input swipe 540 2230 {target_x} {target_y} 135")


def dismiss_catch_screens():
    """Batched 1.1s dismissal of 'POKÉMON PEGO' OK button (540, 1544) + Pokémon Summary ✓ (540, 2320)."""
    adb_shell("input tap 540 1544; sleep 0.85; input tap 540 2320")
    time.sleep(0.55)


def spin_and_collect_stop(x: int, y: int) -> Tuple[bool, str]:
    """Taps a Pokéstop, verifies it actually opened (so it NEVER swipes the map camera or taps
    the map Pokéball!), spins the photodisc, checks for Bag Full banner, and closes cleanly
    with a single settled tap (1.15s wait) so it NEVER double-taps into the map Pokéball menu."""
    adb_tap(x, y, jitter=3, delay=1.05)

    img_open = adb_screencap()
    if img_open is None or is_map_screen(img_open):
        return False, "not_opened"

    if is_encounter_screen(img_open):
        return False, "encounter"

    # Spin photodisc cleanly
    adb_swipe(200, 1150, 880, 1150, duration_ms=160, delay=0.55)

    bag_full = False
    img_spun = adb_screencap()
    if img_spun is not None:
        try:
            import pytesseract
            top_roi = img_spun[220:520, 120:960]
            txt = pytesseract.image_to_string(top_roi).upper()
            if "BOLSA" in txt or "CHEIA" in txt or "LOTAD" in txt:
                bag_full = True
        except Exception:
            pass

    # Tap close X button ONCE and wait 1.15s for zoom-out animation back to map to settle!
    if img_spun is None or not is_map_screen(img_spun):
        adb_tap(540, 2325, jitter=2, delay=1.15)

    return (not bag_full), ("bag_full" if bag_full else "ok")
