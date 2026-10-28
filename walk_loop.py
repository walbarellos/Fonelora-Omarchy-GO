#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Auto-elevação para o ambiente virtual com pyzmq se executado com o Python global
venv_python = Path(__file__).resolve().parent / ".venv/bin/python3"
if venv_python.is_file() and sys.executable != str(venv_python):
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

import json
import math
import random
import time
import zmq

PORT = 17878
ROUTES_FILE = Path(__file__).resolve().parent / "routes_data.json"

# Coordenada da sua casa em Rio Branco (Travessa Marajá, Preventório)
HOME = (-9.975487, -67.821538)

def load_routes():
    if ROUTES_FILE.is_file():
        with open(ROUTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def distance_meters(lat1, lon1, lat2, lon2):
    R = 6371000 # metros
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def run_loop(route_name: str = "tour_centro", speed_mps: float = 1.3):
    routes = load_routes()
    if route_name not in routes:
        print(f"Rota '{route_name}' não encontrada. Opções disponíveis: {list(routes.keys())}")
        route_name = list(routes.keys())[0] if routes else None

    if not route_name:
        print("Erro: Nenhuma rota encontrada em routes_data.json")
        return

    waypoints = [tuple(pt) for pt in routes[route_name]]
    total_km = sum(distance_meters(waypoints[i][0], waypoints[i][1], waypoints[i+1][0], waypoints[i+1][1]) for i in range(len(waypoints)-1)) / 1000.0

    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, 1500)
    sock.setsockopt(zmq.SNDTIMEO, 1500)
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(f"tcp://127.0.0.1:{PORT}")

    step_time = 0.8 # intervalo de atualização em segundos
    step_dist = speed_mps * step_time

    print("=" * 60)
    print(f"🎮 Fonelora Omarchy GO — Circuito Automático de Ruas Reais")
    print(f"🏠 Ponto de Partida e Chegada: Sua Casa (-9.975487, -67.821538)")
    print(f"🗺️  Rota Ativa: [{route_name}]")
    print(f"📍 Total de Waypoints: {len(waypoints)} pontos conectados pelas ruas")
    print(f"📏 Distância total do circuito: {total_km:.2f} km")
    print(f"🚶 Velocidade de caminhada: {speed_mps} m/s (~{speed_mps * 3.6:.1f} km/h)")
    print(f"🔌 Canal ZeroMQ: tcp://127.0.0.1:{PORT}")
    print("=" * 60)

    loop_count = 0
    while True:
        loop_count += 1
        print(f"\n🏃 >>> Iniciando Volta #{loop_count} do Circuito [{route_name}] <<<")
        for i in range(len(waypoints) - 1):
            p1 = waypoints[i]
            p2 = waypoints[i+1]
            total_dist = distance_meters(p1[0], p1[1], p2[0], p2[1])
            steps = max(1, int(total_dist / step_dist))

            if i % 10 == 0 or i == len(waypoints) - 2:
                print(f"[{i+1}/{len(waypoints)-1}] Seguindo pela via: dist={total_dist:.1f}m ({steps} passos)")

            for s in range(steps + 1):
                fraction = s / steps
                # Interpolação com micro-variação humana natural
                jitter_lat = (random.random() - 0.5) * 0.000002
                jitter_lon = (random.random() - 0.5) * 0.000002
                cur_lat = p1[0] + (p2[0] - p1[0]) * fraction + jitter_lat
                cur_lon = p1[1] + (p2[1] - p1[1]) * fraction + jitter_lon

                payload = json.dumps({
                    "Action": "SendPosition",
                    "data": {"Lat": cur_lat, "Lng": cur_lon}
                })

                try:
                    sock.send_string(payload)
                    _ = sock.recv_string()
                except Exception:
                    sock.close()
                    sock = ctx.socket(zmq.REQ)
                    sock.setsockopt(zmq.RCVTIMEO, 1500)
                    sock.setsockopt(zmq.SNDTIMEO, 1500)
                    sock.setsockopt(zmq.LINGER, 0)
                    sock.connect(f"tcp://127.0.0.1:{PORT}")

                time.sleep(step_time)

if __name__ == "__main__":
    # Permite passar o nome da rota e velocidade por linha de comando
    # Exemplo: python walk_loop.py tour_centro 1.3
    # Exemplo: python walk_loop.py tour_maternidade 1.2
    # Exemplo: python walk_loop.py bairro_preventorio 1.1
    route_arg = sys.argv[1] if len(sys.argv) > 1 else "tour_centro"
    speed_arg = float(sys.argv[2]) if len(sys.argv) > 2 else 1.3
    run_loop(route_name=route_arg, speed_mps=speed_arg)
