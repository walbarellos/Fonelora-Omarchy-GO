#!/usr/bin/env python3
"""Fonelora Autonomous Bot Engine (Unified High-Speed Architecture)
Integrates:
  1. GPS Walk Loop with OSRM street transit, Gaussian jitter, and .bot_pause synchronization.
  2. Fast Vision (~1.3s gzip raw screencap):
     - Immediate recovery if already inside combat, Catch OK card, or Pokémon Summary screen.
     - Priority 0: Spin available Orange/Blue Pokéstops in range (strictly ignoring Purple cooldown stops).
     - Priority 1: Engage wild Pokémon spawns, feed Razz Berry, select ball by CP, single continuous throw,
       rapid re-throw on breakout, and <1.5s batched dismissal of OK + Summary ✓.
     - Priority 2: Collect glowing map boxes.
     - Priority 3: Automatic Bag Full cleanup (only time map Pokéball menu is ever opened).
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

# Ensure virtual environment python
_venv = Path(__file__).resolve().parent / ".venv/bin/python3"
if _venv.is_file() and sys.executable != str(_venv):
    os.execv(str(_venv), [str(_venv)] + sys.argv)

# Ensure real-time unbuffered logging for live monitoring
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

import zmq
import pogo_driver

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "bot_config.json"
ROUTES_FILE = BASE / "routes_data.json"
PAUSE_FILE = BASE / ".bot_pause"
STATE_FILE = BASE / ".bot_state.json"
PORT = 17878


class AutonomousBot:
    def __init__(self, route_name: str = "tour_centro", walk_speed_kmh: float = 8.5):
        self.route_name = route_name
        self.walk_speed_kmh = walk_speed_kmh
        self.running = True
        self.current_lat: Optional[float] = None
        self.current_lon: Optional[float] = None
        self.load_config()
        self.load_route()
        self.spun_stops_history: Dict[Tuple[int, int], float] = {}
        self.tapped_spawns_history: Dict[Tuple[int, int], float] = {}
        self.stats = {
            "catches": 0,
            "spins": 0,
            "bag_clears": 0,
            "fled": 0,
        }

    def load_config(self):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except Exception:
            self.config = {}

    def load_route(self):
        with open(ROUTES_FILE, "r", encoding="utf-8") as f:
            routes = json.load(f)
        if self.route_name not in routes:
            self.route_name = list(routes.keys())[0]
        self.waypoints = [tuple(pt) for pt in routes[self.route_name]]

    def publish_status(self, phase: str, detail: str = ""):
        try:
            data = {
                "phase": phase,
                "detail": detail,
                "lat": self.current_lat,
                "lon": self.current_lon,
                "stats": self.stats,
                "timestamp": time.time(),
            }
            STATE_FILE.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    def pause_walk(self):
        PAUSE_FILE.touch(exist_ok=True)

    def resume_walk(self):
        if PAUSE_FILE.exists():
            try:
                PAUSE_FILE.unlink()
            except Exception:
                pass

    def finish_post_catch_to_map(self) -> bool:
        """Rapidly clears 'POKÉMON PEGO' OK card (540, 1544) and Pokémon Summary ✓ (540, 2320)
        until verified back on the main map."""
        for step in range(5):
            img = pogo_driver.adb_screencap()
            if img is None:
                continue
            if pogo_driver.is_map_screen(img):
                return True
            if pogo_driver.is_encounter_screen(img):
                return False
            pogo_driver.dismiss_popups(img)
        img_final = pogo_driver.adb_screencap()
        return bool(img_final is not None and pogo_driver.is_map_screen(img_final))

    def engage_active_combat(self, initial_img) -> bool:
        """Executes fast human-speed combat when on the encounter screen:
        - Normal Pokémon (CP < 550): throws Pokéball #1 IMMEDIATELY (~1.5s from HUD appearing)!
        - Hard Pokémon (CP >= 550) or breakout on attempt 2: feeds Fruta Frambo & selects Great/Ultra Ball.
        """
        combat_start = time.time()
        self.pause_walk()
        cp = pogo_driver.extract_encounter_cp(initial_img)
        min_cp_to_catch = self.config.get("hunt", {}).get("cp_flee", 0)
        print(f"⚔️ [Combat] Batalha aberta! PC: {cp if cp > 0 else 'N/D'}")

        if 0 < cp < min_cp_to_catch:
            print(f"⏩ [Hunt] CP abaixo do filtro ({cp} < {min_cp_to_catch}). Fugindo...")
            pogo_driver.run_away_from_encounter()
            self.stats["fled"] += 1
            self.resume_walk()
            return False

        # Smart Ball Selection by CP (<550 Pokébola sem abrir menu, 550-1199 Great, >=1200 Ultra)
        pogo_driver.select_ball_by_cp(cp)

        # Only feed Fruta Frambo BEFORE Throw #1 if Pokémon is difficult (CP >= 550)!
        berry_fed = False
        if cp >= 550:
            print(f"🍓 [Combat] Pokémon difícil (PC {cp}) -> dando Fruta Frambo antes do arremesso...")
            pogo_driver.feed_berry_in_combat()
            berry_fed = True

        # Continuous single-swipe throw loop (up to 4 attempts)
        for attempt in range(1, 5):
            # If Pokémon broke out of Throw #1 and we haven't fed a berry yet, feed Fruta Frambo on Attempt #2!
            if attempt == 2 and not berry_fed:
                print("🍓 [Combat] Escapou da 1ª bola -> dando Fruta Frambo para garantir captura...")
                pogo_driver.feed_berry_in_combat()
                berry_fed = True

            t0 = time.time()
            since_start = t0 - combat_start
            print(f"🎯 [Combat] Arremesso {attempt}/4 (t+{since_start:.1f}s após abrir combate)...")
            pogo_driver.execute_curveball_throw(attempt=attempt)

            # Wait ~3.2s for flight + ball shakes, then poll fast screencap
            time.sleep(3.2)
            for _poll in range(5):
                img_chk = pogo_driver.adb_screencap()
                if img_chk is None:
                    continue

                if pogo_driver.is_map_screen(img_chk):
                    print("🗺️ [Combat] Retornou ao mapa (Pokémon fugiu ou encontro encerrado).")
                    self.resume_walk()
                    return False

                # Safety: if an item drawer accidentally opened, close it immediately and re-throw
                if pogo_driver.is_item_drawer_open(img_chk):
                    pogo_driver.dismiss_popups(img_chk)
                    break

                if pogo_driver.is_encounter_screen(img_chk):
                    elapsed = time.time() - t0
                    print(f"⚡ [Combat] Bola não prendeu / escapou ({elapsed:.1f}s). Novo arremesso imediato!")
                    break  # Immediately loops to next attempt!

                if pogo_driver.has_catch_ok_button(img_chk) or pogo_driver.has_close_or_check_button(img_chk):
                    print("🎉 [Hunt] POKÉMON CAPTURADO! Fechando OK + Resumo (✓) instantaneamente...")
                    pogo_driver.dismiss_popups(img_chk)
                    self.finish_post_catch_to_map()
                    self.stats["catches"] += 1
                    print(f"✅ [Hunt] De volta ao mapa! Total capturas: {self.stats['catches']}")
                    self.publish_status("walking", f"Captura concluída ({self.stats['catches']} total)")
                    self.resume_walk()
                    return True

                time.sleep(0.9)

        img_end = pogo_driver.adb_screencap()
        if img_end is not None and pogo_driver.is_encounter_screen(img_end):
            print("⏩ [Combat] Limite de 4 arremessos atingido; saindo do encontro para manter fluxo.")
            pogo_driver.run_away_from_encounter()
        else:
            self.finish_post_catch_to_map()

        self.resume_walk()
        return False

    def handle_encounter(self, spawn_coord: Tuple[int, int]) -> bool:
        """Taps a detected map spawn and transitions into active combat with minimal latency."""
        x, y = spawn_coord
        print(f"🔎 [Hunt] Tocando spawn em ({x}, {y})...")
        self.publish_status("hunting", f"Abrindo spawn em ({x}, {y})")
        self.pause_walk()

        # Encounter zoom-in takes ~1.45s; screencap takes ~1.3s -> captures right as HUD lands!
        pogo_driver.adb_tap(x, y, jitter=3, delay=1.45)
        img = pogo_driver.adb_screencap()
        if img is not None and pogo_driver.is_encounter_screen(img):
            return self.engage_active_combat(img)

        # Check if "Sua Coleção de Pokémon está cheia" toast/modal appeared when tapping a spawn!
        if img is not None:
            try:
                import pytesseract
                banner_txt = pytesseract.image_to_string(img[220:650, 100:980]).upper()
                if ("POK" in banner_txt or "COLE" in banner_txt) and ("CHEIA" in banner_txt or "LOTAD" in banner_txt):
                    print("⚠️ [PokéBox] Coleção de Pokémon cheia detectada! Liberando PC < 1000 automaticamente...")
                    self.manage_pokemon_storage(max_cp=999)
                    return False
            except Exception:
                pass

        # If zoom-in animation was still mid-transition (not map, HUD not yet faded in), wait 0.45s
        if img is not None and not pogo_driver.is_map_screen(img):
            if pogo_driver.has_close_or_check_button(img) or pogo_driver.has_catch_ok_button(img):
                pogo_driver.dismiss_popups(img)
                self.resume_walk()
                return False
            time.sleep(0.45)
            img2 = pogo_driver.adb_screencap()
            if img2 is not None and pogo_driver.is_encounter_screen(img2):
                return self.engage_active_combat(img2)
            if img2 is not None and not pogo_driver.is_map_screen(img2):
                pogo_driver.dismiss_popups(img2)

        print("[-] Objeto tocado não abriu batalha. Retomando caminhada.")
        self.resume_walk()
        return False

    def handle_pokestop(self, stop_coord: Tuple[int, int]) -> bool:
        """Opens, verifies, spins, and closes an available Pokéstop cleanly."""
        x, y = stop_coord
        print(f"🌀 [Pokéstop] Abrindo Pokéstop disponível em ({x}, {y})...")
        self.publish_status("restocking", f"Girando Pokéstop em ({x}, {y})")

        ok, status = pogo_driver.spin_and_collect_stop(x, y)
        if status == "encounter":
            print("⚔️ [Pokéstop] Toque abriu um Pokémon sobreposto ao Pokéstop! Capturando...")
            img_enc = pogo_driver.adb_screencap()
            if img_enc is not None and pogo_driver.is_encounter_screen(img_enc):
                return self.engage_active_combat(img_enc)
            return False

        if status == "not_opened":
            print("[-] Pokéstop fora de alcance ou não abriu (nenhum swipe executado no mapa).")
            return False

        if status == "bag_full":
            print("⚠️ [Pokéstop] Notificação de BOLSA CHEIA detectada! Limpando inventário agora...")
            self.manage_inventory()
            return False

        self.stats["spins"] += 1
        print(f"✨ [Pokéstop] Fotodisco coletado e fechado! Total giros: {self.stats['spins']}")
        self.publish_status("walking", f"Pokéstop coletado ({self.stats['spins']} total)")
        return True

    def manage_inventory(self):
        """ONLY place in the entire codebase allowed to tap the map Pokéball menu (540, 2300)."""
        print("🎒 [Mochila] Abrindo menu da Pokébola para descartar itens excedentes...")
        self.publish_status("inventory", "Descartando itens excedentes")
        self.pause_walk()
        time.sleep(0.3)

        img = pogo_driver.adb_screencap()
        if img is not None and not pogo_driver.is_map_screen(img):
            self.finish_post_catch_to_map()

        # 1. Open Pokéball Menu -> 2. Tap ITENS (840, 2070)
        pogo_driver.adb_tap(540, 2300, jitter=2, delay=0.9)
        pogo_driver.adb_tap(840, 2070, jitter=3, delay=1.6)

        # 3. Tap trash can on top potion row (999, 572)
        pogo_driver.adb_tap(999, 572, jitter=2, delay=0.9)

        # 4. Increase discard quantity (+ at 792, 1206) rapidly via single shell loop & confirm SIM (540, 1360)
        plus_taps = "; ".join(["input tap 792 1206"] * 12)
        pogo_driver.adb_shell(f"{plus_taps}; sleep 0.3; input tap 540 1360")
        time.sleep(1.1)

        # 5. Close Items Bag at (540, 2325)
        pogo_driver.adb_tap(540, 2325, jitter=2, delay=0.8)
        self.finish_post_catch_to_map()

        self.stats["bag_clears"] += 1
        print(f"✨ [Mochila] Espaço liberado na bolsa! Limpezas: {self.stats['bag_clears']}")
        self.resume_walk()

    def manage_pokemon_storage(self, max_cp: int = 999):
        """Automatically mass-transfers non-special Pokémon up to max_cp (e.g. pc-999).
        Uses Pokémon GO's native SELECIONAR TUDO (which automatically protects Shinies,
        Legendaries, Mythicals, Favorites, Buddies, and Gym Defenders) and favorites any
        last Dynamax Pokémon first so the batch transfer succeeds in 1 click."""
        print(f"📦 [PokéBox] Iniciando transferência em massa segura (pc-{max_cp})...")
        self.publish_status("inventory", f"Liberando Pokémons PC <= {max_cp}")
        self.pause_walk()
        time.sleep(0.4)

        img = pogo_driver.adb_screencap()
        if img is not None and not pogo_driver.is_map_screen(img):
            self.finish_post_catch_to_map()

        # 1. Open Pokéball Menu (540, 2300) -> POKÉMON storage (240, 2070)
        pogo_driver.adb_tap(540, 2300, jitter=2, delay=0.95)
        pogo_driver.adb_tap(240, 2070, jitter=3, delay=2.20)

        # 2. Protect last Dynamax Pokémon if un-favorited so SELECIONAR TUDO never blocks:
        pogo_driver.adb_shell('input tap 500 355; sleep 0.85; input text "dinamax"; sleep 0.4; input keyevent 66')
        time.sleep(1.0)
        # Tap first Dynamax if present, favorite star at top-right (985, 195), close summary (540, 2315)
        img_dmax = pogo_driver.adb_screencap()
        if img_dmax is not None:
            # Check if at least 1 sprite tile exists at (195, 720) (non-uniform white)
            if img_dmax[640:800, 115:275].std() > 14:
                pogo_driver.adb_tap(195, 720, jitter=2, delay=1.1)
                # Only tap favorite star if not already yellow/gold
                star_roi = img_dmax = pogo_driver.adb_screencap()
                if star_roi is not None:
                    hsv_star = pogo_driver.cv2.cvtColor(star_roi[150:250, 930:1030], pogo_driver.cv2.COLOR_BGR2HSV)
                    if (pogo_driver.cv2.inRange(hsv_star, (15, 120, 180), (35, 255, 255)) > 0).mean() < 0.05:
                        pogo_driver.adb_tap(982, 198, jitter=2, delay=0.5)
                    pogo_driver.adb_tap(540, 2315, jitter=2, delay=1.0)
        # Clear 'dinamax' search (tap X at 980, 355)
        pogo_driver.adb_tap(980, 355, jitter=2, delay=0.7)

        # 3. Filter pc-{max_cp}, long-press first Pokémon, tap SELECIONAR TUDO, TRANSFERIR, Confirm
        pogo_driver.adb_shell(
            f'input tap 500 355; sleep 0.85; input text "pc-{max_cp}"; sleep 0.4; input keyevent 66'
        )
        time.sleep(1.0)
        pogo_driver.adb_shell(
            "input swipe 195 700 195 700 950; sleep 0.85; "
            "input tap 810 175; sleep 0.90; "
            "input tap 540 2310; sleep 1.00; "
            "input tap 500 1380"
        )
        time.sleep(1.8)

        # 4. Close Pokémon storage back to map
        pogo_driver.adb_tap(980, 355, jitter=2, delay=0.5)
        pogo_driver.adb_tap(540, 2315, jitter=2, delay=1.15)
        self.finish_post_catch_to_map()
        print(f"✅ [PokéBox] Pokémons PC <= {max_cp} transferidos com segurança (Brilhantes/Míticos/Favoritos preservados)!")
        self.resume_walk()

    def vision_cycle(self):
        """Single perception-action tick (~1.4s on idle walk)."""
        img = pogo_driver.adb_screencap()
        if img is None:
            return

        # Immediate combat handling if already inside an encounter!
        if pogo_driver.is_encounter_screen(img):
            self.engage_active_combat(img)
            return

        # Immediate dismissal if on Catch OK card, Pokémon Summary ✓, or open Stop/Modal
        if not pogo_driver.is_map_screen(img):
            pogo_driver.dismiss_popups(img)
            self.finish_post_catch_to_map()
            return

        now = time.time()

        # Prune expired cooldown entries
        self.spun_stops_history = {k: t for k, t in self.spun_stops_history.items() if now - t < 300}
        self.tapped_spawns_history = {k: t for k, t in self.tapped_spawns_history.items() if now - t < 45}

        # Priority 0: Available Orange/Blue Pokéstops within interaction ring (~360px of avatar 505, 1585)
        stops = pogo_driver.detect_pokestops(img)
        interactive_stops = [
            s for s in stops if (s[0] - 505) ** 2 + (s[1] - 1585) ** 2 < 360 ** 2
        ]
        fresh_stops = [
            s for s in interactive_stops
            if not any(abs(s[0] - hx) < 90 and abs(s[1] - hy) < 90 for (hx, hy) in self.spun_stops_history)
        ]
        if fresh_stops:
            best_stop = fresh_stops[0]
            self.spun_stops_history[(best_stop[0], best_stop[1])] = now
            self.handle_pokestop((best_stop[0], best_stop[1]))
            return

        # Priority 1: Wild Pokémon Spawns (filtered by 45s tap memory so non-spawns are never re-tapped)
        spawns = pogo_driver.detect_spawns(img)
        fresh_spawns = [
            s for s in spawns
            if not any(abs(s[0] - hx) < 75 and abs(s[1] - hy) < 75 for (hx, hy) in self.tapped_spawns_history)
        ]
        if fresh_spawns:
            best_spawn = fresh_spawns[0]
            self.tapped_spawns_history[(best_spawn[0], best_spawn[1])] = now
            self.handle_encounter((best_spawn[0], best_spawn[1]))
            return

        # Priority 2: Glowing Map Boxes
        boxes = pogo_driver.detect_glowing_boxes(img)
        fresh_boxes = [
            b for b in boxes
            if not any(abs(b[0] - hx) < 70 and abs(b[1] - hy) < 70 for (hx, hy) in self.tapped_spawns_history)
        ]
        if fresh_boxes:
            box = fresh_boxes[0]
            self.tapped_spawns_history[(box[0], box[1])] = now
            print(f"🎁 [Caixa] Coletando caixa brilhante no mapa em ({box[0]}, {box[1]})...")
            pogo_driver.adb_tap(box[0], box[1], jitter=3, delay=0.6)
            return

    def gps_walk_worker(self):
        """Worker thread executing organic GPS route movement."""
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.RCVTIMEO, 1500)
        sock.setsockopt(zmq.SNDTIMEO, 1500)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(f"tcp://127.0.0.1:{PORT}")

        try:
            sock.send_string(json.dumps({"Action": "CurrentPosition"}))
            res = json.loads(sock.recv_string())
            if res.get("State") == 200 and "data" in res:
                self.current_lat = float(res["data"]["Lat"])
                self.current_lon = float(res["data"]["Lng"])
        except Exception:
            pass

        if not self.current_lat or not self.current_lon:
            self.current_lat, self.current_lon = self.waypoints[0]

        print(f"🚶 [WalkEngine] Inicializado na posição {self.current_lat:.6f}, {self.current_lon:.6f}")

        # Start from closest waypoint to current position so we don't rubberband across town!
        wp_idx = min(
            range(len(self.waypoints)),
            key=lambda i: math.hypot(self.waypoints[i][0] - self.current_lat, self.waypoints[i][1] - self.current_lon),
        )
        total_wps = len(self.waypoints)

        while self.running:
            if PAUSE_FILE.exists():
                j_lat = self.current_lat + random.gauss(0.0, 0.000003)
                j_lon = self.current_lon + random.gauss(0.0, 0.000003)
                try:
                    payload = json.dumps({"Action": "SendPosition", "data": {"Lat": round(j_lat, 7), "Lng": round(j_lon, 7)}})
                    sock.send_string(payload)
                    sock.recv_string()
                except Exception:
                    pass
                time.sleep(1.2)
                continue

            target_pt = self.waypoints[wp_idx]
            dlat = target_pt[0] - self.current_lat
            dlon = target_pt[1] - self.current_lon
            dist_m = math.hypot(dlat, dlon) * 111320.0

            if dist_m < 3.5:
                wp_idx = (wp_idx + 1) % total_wps
                continue

            speed_kmh = self.walk_speed_kmh * random.uniform(0.9, 1.1)
            step_mps = speed_kmh / 3.6
            step_duration = random.uniform(0.7, 1.0)
            step_dist_m = step_mps * step_duration

            frac = min(1.0, step_dist_m / dist_m)
            self.current_lat += dlat * frac
            self.current_lon += dlon * frac

            send_lat = self.current_lat + random.gauss(0.0, 0.000004)
            send_lon = self.current_lon + random.gauss(0.0, 0.000004)

            try:
                payload = json.dumps({"Action": "SendPosition", "data": {"Lat": round(send_lat, 7), "Lng": round(send_lon, 7)}})
                sock.send_string(payload)
                sock.recv_string()
            except Exception:
                try:
                    sock.close()
                    sock = ctx.socket(zmq.REQ)
                    sock.setsockopt(zmq.RCVTIMEO, 1500)
                    sock.setsockopt(zmq.SNDTIMEO, 1500)
                    sock.setsockopt(zmq.LINGER, 0)
                    sock.connect(f"tcp://127.0.0.1:{PORT}")
                except Exception:
                    pass

            self.publish_status("walking", f"Ponto {wp_idx+1}/{total_wps} ({speed_kmh:.1f} km/h)")
            time.sleep(step_duration)

    def run(self):
        print("=" * 65)
        print("🤖 INICIANDO BOT AUTÔNOMO FONELORA-OMARCHY-GO (TURBO VISION)")
        print(f"📍 Rota: {self.route_name} | Velocidade: {self.walk_speed_kmh} km/h")
        print("🌀 Prioridade 0: Girar Pokéstops Laranja/Azul (ignora Roxos)")
        print("🎯 Prioridade 1: Caçar Pokémons (Fruta + Arremesso Contínuo + Fecho <1.5s)")
        print("🎒 Prioridade 2: Caixas Brilhantes & Descarte Automático se Lotado")
        print("=" * 65)

        self.resume_walk()
        walk_thread = threading.Thread(target=self.gps_walk_worker, daemon=True)
        walk_thread.start()

        try:
            while self.running:
                self.vision_cycle()
                time.sleep(0.4)
        except KeyboardInterrupt:
            print("\nParando bot autônomo...")
            self.running = False
            self.resume_walk()


if __name__ == "__main__":
    selected_route = sys.argv[1] if len(sys.argv) > 1 else "shinjuku_tokyo"
    bot = AutonomousBot(route_name=selected_route, walk_speed_kmh=8.5)
    bot.run()
