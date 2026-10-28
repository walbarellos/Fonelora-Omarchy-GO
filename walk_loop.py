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
import urllib.request
import zmq

PORT = 17878
ROUTES_FILE = Path(__file__).resolve().parent / "routes_data.json"
HOME = (-9.975487, -67.821538)

def distance_meters(lat1, lon1, lat2, lon2):
    R = 6371000 # metros
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def get_current_position(sock):
    """Consulta onde o avatar está atualmente no jogo via ZMQ."""
    try:
        sock.send_string(json.dumps({"Action": "CurrentPosition"}))
        raw = sock.recv_string()
        data = json.loads(raw)
        if data.get("State") == 200 and "data" in data:
            lat = float(data["data"]["Lat"])
            lng = float(data["data"]["Lng"])
            if lat != 0.0 and lng != 0.0:
                return (lat, lng)
    except Exception:
        pass
    return None

def fetch_street_route(from_pt, to_pt):
    """Busca o trajeto real pelas ruas entre dois pontos usando OSRM."""
    url = f"http://router.project-osrm.org/route/v1/foot/{from_pt[1]},{from_pt[0]};{to_pt[1]},{to_pt[0]}?overview=full&geometries=geojson"
    req = urllib.request.Request(url, headers={"User-Agent": "FoneloraOmarchy-AutoTransit/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read().decode())
            coords = d["routes"][0]["geometry"]["coordinates"]
            # Converter [lon, lat] -> (lat, lon)
            return [(c[1], c[0]) for c in coords]
    except Exception as e:
        print(f"[Transit] Aviso: Rota OSRM falhou ({e}), usando aproximação direta.")
        return [from_pt, to_pt]

def send_step(sock, lat, lon):
    jitter_lat = (random.random() - 0.5) * 0.000002
    jitter_lon = (random.random() - 0.5) * 0.000002
    payload = json.dumps({
        "Action": "SendPosition",
        "data": {"Lat": lat + jitter_lat, "Lng": lon + jitter_lon}
    })
    sock.send_string(payload)
    return sock.recv_string()

def run_loop(route_name: str = "tour_centro", walk_speed_kmh: float = 8.0, transit_speed_kmh: float = 28.0):
    routes_file = ROUTES_FILE
    if not routes_file.is_file():
        print("Erro: Arquivo routes_data.json não encontrado.")
        return

    with open(routes_file, "r", encoding="utf-8") as f:
        routes = json.load(f)

    if route_name not in routes:
        print(f"Rota '{route_name}' não encontrada. Opções disponíveis: {list(routes.keys())}")
        route_name = list(routes.keys())[0] if routes else None

    target_waypoints = [tuple(pt) for pt in routes[route_name]]
    first_target_pt = target_waypoints[0]

    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, 1500)
    sock.setsockopt(zmq.SNDTIMEO, 1500)
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(f"tcp://127.0.0.1:{PORT}")

    print("=" * 65)
    print("🎮 Fonelora Omarchy GO — Sistema Inteligente de Deslocamento")
    print(f"📍 Rota Selecionada: [{route_name}] ({len(target_waypoints)} pontos)")
    print("=" * 65)

    # 1. Identificar posição atual
    print("[1/3] Detectando posição atual do avatar no Pokémon GO...")
    current_pos = get_current_position(sock)
    if not current_pos:
        print("[-] Não foi possível obter posição do jogo, assumindo início padrão.")
        current_pos = first_target_pt
    else:
        print(f"[+] Posição atual detectada: {current_pos[0]:.6f}, {current_pos[1]:.6f}")

    dist_to_start = distance_meters(current_pos[0], current_pos[1], first_target_pt[0], first_target_pt[1])

    # 2. Se estiver longe do início da rota (> 15 metros), transitar rápido pelas ruas até lá
    if dist_to_start > 15.0:
        transit_mps = transit_speed_kmh / 3.6 # ex: 28 km/h = 7.7 m/s
        step_time = 0.5
        step_dist = transit_mps * step_time

        print(f"\n🚗 [2/3] DESLOCAMENTO INTELIGENTE PELAS RUAS:")
        print(f"   Distância até o início da rota: {dist_to_start:.1f} metros")
        print(f"   Velocidade de trânsito: {transit_speed_kmh:.1f} km/h (imitação de bike/carro)")

        transit_path = fetch_street_route(current_pos, first_target_pt)
        print(f"   Traçado pelas ruas: {len(transit_path)} vértices.")

        for i in range(len(transit_path) - 1):
            p1 = transit_path[i]
            p2 = transit_path[i+1]
            seg_dist = distance_meters(p1[0], p1[1], p2[0], p2[1])
            steps = max(1, int(seg_dist / step_dist))
            for s in range(steps + 1):
                frac = s / steps
                cur_lat = p1[0] + (p2[0] - p1[0]) * frac
                cur_lon = p1[1] + (p2[1] - p1[1]) * frac
                try:
                    send_step(sock, cur_lat, cur_lon)
                except Exception:
                    sock.close()
                    sock = ctx.socket(zmq.REQ)
                    sock.setsockopt(zmq.RCVTIMEO, 1500)
                    sock.setsockopt(zmq.SNDTIMEO, 1500)
                    sock.setsockopt(zmq.LINGER, 0)
                    sock.connect(f"tcp://127.0.0.1:{PORT}")
                time.sleep(step_time)

        print("[✓] Chegada ao ponto inicial da rota concluída com sucesso!\n")
    else:
        print("[2/3] Você já está próximo do ponto inicial. Iniciando rota diretamente.\n")

    # 3. Executar o circuito principal em loop contínuo
    walk_mps = walk_speed_kmh / 3.6
    step_time = 0.8
    step_dist = walk_mps * step_time

    print(f"🚶 [3/3] INICIANDO CIRCUITO [{route_name}]")
    print(f"   Velocidade de caminhada: {walk_speed_kmh:.1f} km/h ({walk_mps:.1f} m/s)")
    print(f"   Modo: Circuito Contínuo pelas Ruas")

    loop_count = 0
    while True:
        loop_count += 1
        print(f"\n--- Volta #{loop_count} do Circuito [{route_name}] ---")
        for i in range(len(target_waypoints) - 1):
            p1 = target_waypoints[i]
            p2 = target_waypoints[i+1]
            seg_dist = distance_meters(p1[0], p1[1], p2[0], p2[1])
            steps = max(1, int(seg_dist / step_dist))

            if i % 15 == 0 or i == len(target_waypoints) - 2:
                print(f"Progresso: ponto {i+1}/{len(target_waypoints)-1} ({seg_dist:.1f}m)")

            for s in range(steps + 1):
                frac = s / steps
                cur_lat = p1[0] + (p2[0] - p1[0]) * frac
                cur_lon = p1[1] + (p2[1] - p1[1]) * frac
                try:
                    send_step(sock, cur_lat, cur_lon)
                except Exception:
                    sock.close()
                    sock = ctx.socket(zmq.REQ)
                    sock.setsockopt(zmq.RCVTIMEO, 1500)
                    sock.setsockopt(zmq.SNDTIMEO, 1500)
                    sock.setsockopt(zmq.LINGER, 0)
                    sock.connect(f"tcp://127.0.0.1:{PORT}")
                time.sleep(step_time)

if __name__ == "__main__":
    # Argumentos opcionais:
    # python walk_loop.py <rota> <velocidade_caminhada_kmh> <velocidade_transito_kmh>
    # Ex: python walk_loop.py tour_centro 9.0 28.0
    r_name = sys.argv[1] if len(sys.argv) > 1 else "tour_centro"
    w_spd = float(sys.argv[2]) if len(sys.argv) > 2 else 9.0   # ~9 km/h (caminhada rápida / jogging leve seguro)
    t_spd = float(sys.argv[3]) if len(sys.argv) > 3 else 28.0  # 28 km/h para deslocamento rápido pelas ruas
    run_loop(route_name=r_name, walk_speed_kmh=w_spd, transit_speed_kmh=t_spd)
