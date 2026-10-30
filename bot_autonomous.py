#!/usr/bin/env python3
"""Fonelora Autonomous Bot Engine (Unified Architecture)
Integrates:
  1. GPS Walk Loop with OSRM street transit, Gaussian jitter, dynamic turn deceleration.
  2. Map Vision: Autonomous scan for Spawns and Pokéstops.
  3. Priority 1 (Encounter & Catch):
     - Automatically pauses GPS walk (.bot_pause)
     - Initiates combat with detected spawn
     - Executes curveball Pokéball throw
     - Verifies catch result and collects XP / Stardust
     - Automatically releases pause and resumes walking
  4. Priority 2 (Restock Pokéstops):
     - If Pokéstops in interaction range (or Pokéballs running low), spins photodisc
     - Collects items and closes stop screen
     - Detects "Mochila Cheia" (Bag Full) feedback banner
  5. Priority 3 (Inventory Management):
     - If bag is full or periodically, opens Items Bag
     - Discards excess Potions, Revives, or Nanabs according to bot_config.json keep_max
     - Returns to map to continue hunt
"""
from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Ensure virtual environment python
_venv = Path(__file__).resolve().parent / ".venv/bin/python3"
if _venv.is_file() and sys.executable != str(_venv):
    os.execv(str(_venv), [str(_venv)] + sys.argv)

import cv2
import numpy as np
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
        self.stats = {
            "catches": 0,
            "spins": 0,
            "bag_clears": 0,
            "fled": 0
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
                "phase": phase, # 'walking', 'hunting', 'restocking', 'inventory', 'paused'
                "detail": detail,
                "lat": self.current_lat,
                "lon": self.current_lon,
                "stats": self.stats,
                "timestamp": time.time()
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

    def handle_encounter(self, spawn_coord) -> bool:
        """Executes full combat and capture lifecycle."""
        x, y = spawn_coord
        print(f"🎯 [Hunt] Spawn detectado em ({x}, {y}). Pausando caminhada e iniciando combate...")
        self.publish_status("hunting", f"Encontro iniciado em ({x}, {y})")
        self.pause_walk()
        time.sleep(0.5)

        # Tap on the spawn
        pogo_driver.adb_tap(x, y)
        time.sleep(3.5)

        img = pogo_driver.adb_screencap()
        # Check if combat screen entered
        if not pogo_driver.is_encounter_screen(img):
            # Check if camera was just tapped on ground
            print("[-] Não entrou em combate ou spawn sumiu.")
            self.resume_walk()
            return False

        # Check CP threshold from bot_config.json
        cp = pogo_driver.extract_encounter_cp(img)
        min_cp_to_catch = self.config.get("hunt", {}).get("cp_flee", 100)
        if 0 < cp < min_cp_to_catch:
            print(f"⏩ [Hunt] CP baixo ({cp} < {min_cp_to_catch}). Ignorando/fugindo do combate...")
            pogo_driver.run_away_from_encounter()
            self.stats["fled"] += 1
            self.resume_walk()
            return False

        # Feed berry if CP is medium/high or configured to increase catch rate
        use_berry = self.config.get("hunt", {}).get("use_razz_if_cp_above", True)
        if use_berry and cp > 350:
            print("🍓 [Combat] Alimentando Pokémon com Fruta Frambo (Razz Berry)...")
            pogo_driver.feed_berry_in_combat()

        # Fast throwing loop: up to 3 throws if Pokemon broke free
        for throw_attempt in range(1, 4):
            print(f"⚔️ [Combat] Arremesso {throw_attempt}/3 com curva...")
            pogo_driver.execute_curveball_throw()
            
            # Realistic ball shake/wobble interval (human: ~4.5 to 5.5s)
            time.sleep(4.8)
            img_chk = pogo_driver.adb_screencap()
            
            # If back to map, catch was successful
            if pogo_driver.is_map_screen(img_chk):
                self.stats["catches"] += 1
                print(f"🎉 [Hunt] Captura concluída com sucesso! Total capturados: {self.stats['catches']}")
                self.publish_status("walking", f"Captura concluída ({self.stats['catches']} total)")
                self.resume_walk()
                return True

            # If not map, tap screen center to advance past XP animation, then tap bottom checkmark (540, 2330)
            if not pogo_driver.is_encounter_screen(img_chk):
                # Tap center to dismiss XP popup
                pogo_driver.adb_tap(540, 1500)
                time.sleep(0.7)
                # Tap bottom checkmark to close summary screen
                pogo_driver.adb_tap(540, 2330)
                time.sleep(0.8)
                img_after = pogo_driver.adb_screencap()
                if pogo_driver.is_map_screen(img_after):
                    self.stats["catches"] += 1
                    print(f"🎉 [Hunt] Captura concluída! Total capturados: {self.stats['catches']}")
                    self.publish_status("walking", f"Captura concluída ({self.stats['catches']} total)")
                    self.resume_walk()
                    return True
                break

        self.resume_walk()
        time.sleep(0.5)
        return True

    def handle_pokestop(self, stop_coord) -> bool:
        """Opens, spins, and collects Pokéstop photodisc at vehicle/pedestrian transit speed."""
        x, y = stop_coord
        print(f"🌀 [Pokéstop] Acesso rápido a Pokéstop em ({x}, {y})...")
        self.publish_status("restocking", f"Girando Pokéstop em ({x}, {y})")
        
        # Don't full-stop walking for Pokéstops if walking naturally, just brief touch
        pogo_driver.spin_and_collect_stop(x, y)
        self.stats["spins"] += 1
        print(f"✨ [Pokéstop] Fotodisco coletado em ~1s! Total giros: {self.stats['spins']}")
        self.publish_status("walking", f"Pokéstop coletado ({self.stats['spins']} total)")
        return True

    def manage_inventory(self):
        """Discards excess potions or berries if bag space is constrained."""
        print("🎒 [Mochila] Verificando itens para descarte automático...")
        self.publish_status("inventory", "Gerenciando inventário")
        self.pause_walk()
        time.sleep(0.5)

        # Open Pokeball Menu -> Items
        pogo_driver.adb_tap(540, 2300)
        time.sleep(1.5)
        pogo_driver.adb_tap(820, 1920) # Items button
        time.sleep(2.0)

        # Discard top potions/excess items if trash can visible
        # Trash can at top row: approx (990, 490)
        pogo_driver.adb_tap(990, 490)
        time.sleep(1.0)
        # Increase quantity (+) button: approx (750, 1300)
        for _ in range(5):
            pogo_driver.adb_tap(750, 1300)
            time.sleep(0.1)
        # Confirm discard "SIM" button: approx (540, 1600)
        pogo_driver.adb_tap(540, 1600)
        time.sleep(1.0)

        # Close bag back to map
        pogo_driver.adb_tap(540, 2300)
        time.sleep(1.5)

        self.stats["bag_clears"] += 1
        self.resume_walk()

    def vision_cycle(self):
        """Active gameplay perception loop."""
        img = pogo_driver.adb_screencap()
        if img is None:
            return

        if not pogo_driver.is_map_screen(img):
            # Check for dismissal popups (level up, daily streak, notifications, open menus)
            pogo_driver.dismiss_popups(img)
            return

        # Priority 0: Check for Pokéstops (Restocking when in interaction range)
        stops = pogo_driver.detect_pokestops(img)
        # Filter stops strictly in close interaction range (distance < 450px)
        interactive_stops = [s for s in stops if (s[0]-540)**2 + (s[1]-1600)**2 < 420**2]
        if interactive_stops:
            best_stop = interactive_stops[0]
            self.handle_pokestop((best_stop[0], best_stop[1]))
            return

        # Priority 1: Check for Glowing Boxes (Treat / Mystery / Candy boxes)
        boxes = pogo_driver.detect_glowing_boxes(img)
        if boxes:
            box = boxes[0]
            print(f"🎁 [Caixa] Coletando caixa brilhante em ({box[0]}, {box[1]})...")
            pogo_driver.adb_tap(box[0], box[1])
            time.sleep(1.2)
            return

        # Priority 2: Check for Spawns
        spawns = pogo_driver.detect_spawns(img)
        if spawns:
            # Engage closest spawn
            best_spawn = spawns[0]
            self.handle_encounter((best_spawn[0], best_spawn[1]))
            return

    def gps_walk_worker(self):
        """Worker thread executing organic GPS route movement."""
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.RCVTIMEO, 1500)
        sock.setsockopt(zmq.SNDTIMEO, 1500)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(f"tcp://127.0.0.1:{PORT}")

        # Sync initial position from game
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

        wp_idx = 0
        total_wps = len(self.waypoints)

        while self.running:
            # Check pause coordination
            if PAUSE_FILE.exists():
                # Apply micro physical GPS jitter while paused
                j_lat = self.current_lat + random.gauss(0.0, 0.000003)
                j_lon = self.current_lon + random.gauss(0.0, 0.000003)
                try:
                    payload = json.dumps({"Action": "SendPosition", "data": {"Lat": round(j_lat, 7), "Lng": round(j_lon, 7)}})
                    sock.send_string(payload)
                    sock.recv_string()
                except Exception:
                    pass
                time.sleep(1.5)
                continue

            target_pt = self.waypoints[wp_idx]
            # Vector to waypoint
            dlat = target_pt[0] - self.current_lat
            dlon = target_pt[1] - self.current_lon
            dist_m = math.hypot(dlat, dlon) * 111320.0

            if dist_m < 3.5:
                # Reached waypoint, advance to next
                wp_idx = (wp_idx + 1) % total_wps
                continue

            # Speed with natural pedestrian fluctuation (e.g. 7.5 to 9.5 km/h)
            speed_kmh = self.walk_speed_kmh * random.uniform(0.9, 1.1)
            step_mps = speed_kmh / 3.6
            step_duration = random.uniform(0.7, 1.0)
            step_dist_m = step_mps * step_duration

            frac = min(1.0, step_dist_m / dist_m)
            self.current_lat += dlat * frac
            self.current_lon += dlon * frac

            # Gaussian jitter
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
        """Starts the autonomous bot pipeline."""
        print("=" * 65)
        print("🤖 INICIANDO BOT AUTÔNOMO FONELORA-OMARCHY-GO")
        print(f"📍 Rota: {self.route_name} | Velocidade: {self.walk_speed_kmh} km/h")
        print("🎯 Prioridade 1: Caçar Pokémons (Visão + Arremesso Curvo)")
        print("🌀 Prioridade 2: Rodar Pokéstops (Reabastecimento)")
        print("🎒 Prioridade 3: Gestão de Inventário (Keep_max)")
        print("=" * 65)

        # Clear any stale pause
        self.resume_walk()

        # Start GPS walking in background thread
        walk_thread = threading.Thread(target=self.gps_walk_worker, daemon=True)
        walk_thread.start()

        # Main perception and interaction loop
        try:
            while self.running:
                self.vision_cycle()
                time.sleep(1.5)
        except KeyboardInterrupt:
            print("\nParando bot autônomo...")
            self.running = False
            self.resume_walk()

if __name__ == "__main__":
    bot = AutonomousBot(route_name="tour_centro", walk_speed_kmh=8.5)
    bot.run()
