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
    # Jitter espacial realista de GPS (variação de ~0.5m a 1.2m típica de satélites civis)
    jitter_lat = (random.random() - 0.5) * 0.000010
    jitter_lon = (random.random() - 0.5) * 0.000010
    payload = json.dumps({
        "Action": "SendPosition",
        "data": {"Lat": round(lat + jitter_lat, 7), "Lng": round(lon + jitter_lon, 7)}
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

    base_waypoints = [tuple(pt) for pt in routes[route_name]]
    first_target_pt = base_waypoints[0]

    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, 1500)
    sock.setsockopt(zmq.SNDTIMEO, 1500)
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(f"tcp://127.0.0.1:{PORT}")

    print("=" * 65)
    print("🎮 Fonelora Omarchy GO — Sistema Orgânico com Ruído Humano")
    print(f"📍 Rota Base: [{route_name}] ({len(base_waypoints)} pontos)")
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
        print(f"\n🚗 [2/3] DESLOCAMENTO INTELIGENTE PELAS RUAS:")
        print(f"   Distância até o início da rota: {dist_to_start:.1f} metros")
        print(f"   Velocidade média de trânsito: ~{transit_speed_kmh:.1f} km/h (com variações de trânsito)")

        transit_path = fetch_street_route(current_pos, first_target_pt)
        print(f"   Traçado pelas ruas: {len(transit_path)} vértices.")

        for i in range(len(transit_path) - 1):
            p1 = transit_path[i]
            p2 = transit_path[i+1]
            seg_dist = distance_meters(p1[0], p1[1], p2[0], p2[1])

            # Variação dinâmica de velocidade no trânsito (semáforos, curvas: 22 a 32 km/h)
            current_transit_kmh = transit_speed_kmh * random.uniform(0.85, 1.15)
            transit_mps = current_transit_kmh / 3.6
            step_time = random.uniform(0.4, 0.6)
            step_dist = transit_mps * step_time

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

    # 3. Executar o circuito principal em loop contínuo com micro-ruído e variações humanas
    print(f"🚶 [3/3] INICIANDO CIRCUITO ORGÂNICO [{route_name}]")
    print(f"   Velocidade base: {walk_speed_kmh:.1f} km/h")
    print(f"   Comportamento: Velocidade flutuante, pausas de Pokéstops e desvios de calçada.")

    loop_count = 0
    while True:
        loop_count += 1
        
        # Em voltas alternadas, decide se faz sentido inverter o sentido (ida e volta)
        # para não parecer um autômato girando sempre no mesmo sentido
        waypoints = list(base_waypoints)
        if loop_count % 3 == 0:
            print(f"\n🔄 Volta #{loop_count}: Invertendo sentido do percurso para variação orgânica!")
            waypoints = list(reversed(waypoints))
        else:
            print(f"\n--- Volta #{loop_count} do Circuito [{route_name}] ---")

        for i in range(len(waypoints) - 1):
            p1 = waypoints[i]
            p2 = waypoints[i+1]
            seg_dist = distance_meters(p1[0], p1[1], p2[0], p2[1])

            # Variação humana de caminhada:
            # 1. Velocidade flutua entre -20% e +25% a cada trecho (passo humano não é metrônomo)
            current_walk_kmh = walk_speed_kmh * random.uniform(0.78, 1.22)
            walk_mps = current_walk_kmh / 3.6
            
            # 2. Variação no tempo de envio de pacotes (0.65s a 0.95s)
            step_time = random.uniform(0.65, 0.95)
            step_dist = walk_mps * step_time
            steps = max(1, int(seg_dist / step_dist))

            if i % 15 == 0 or i == len(waypoints) - 2:
                print(f"Progresso: ponto {i+1}/{len(waypoints)-1} ({seg_dist:.1f}m) @ {current_walk_kmh:.1f} km/h")

            # 3. Micro-desvio de calçada (cada volta caminha num lado da rua / calçada ligeiramente diferente)
            offset_lat = (random.random() - 0.5) * 0.000015
            offset_lon = (random.random() - 0.5) * 0.000015

            for s in range(steps + 1):
                frac = s / steps
                cur_lat = p1[0] + (p2[0] - p1[0]) * frac + offset_lat
                cur_lon = p1[1] + (p2[1] - p1[1]) * frac + offset_lon
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

            # 4. Pausas orgânicas humanas simuladas:
            # - 10% de chance de parar 4 a 8s (capturar um Pokémon ou rodar Pokéstop)
            # - 2% de chance de parar 12 a 22s (mochila / checar IV)
            roll = random.random()
            if roll < 0.02:
                pause_s = random.uniform(12.0, 22.0)
                print(f"   [Pausa humana] Parou {pause_s:.1f}s (simulando captura demorada/mochila)...")
                t_end = time.time() + pause_s
                while time.time() < t_end:
                    try:
                        send_step(sock, p2[0], p2[1])
                    except Exception:
                        pass
                    time.sleep(random.uniform(0.8, 1.4))
            elif roll < 0.12:
                pause_s = random.uniform(3.5, 7.5)
                t_end = time.time() + pause_s
                while time.time() < t_end:
                    try:
                        send_step(sock, p2[0], p2[1])
                    except Exception:
                        pass
                    time.sleep(random.uniform(0.8, 1.2))

if __name__ == "__main__":
    # Argumentos opcionais:
    # python walk_loop.py <rota> <velocidade_caminhada_kmh> <velocidade_transito_kmh>
    # Ex: python walk_loop.py tour_centro 9.0 28.0
    r_name = sys.argv[1] if len(sys.argv) > 1 else "tour_centro"
    w_spd = float(sys.argv[2]) if len(sys.argv) > 2 else 9.0   # ~9 km/h (caminhada rápida / jogging leve seguro)
    t_spd = float(sys.argv[3]) if len(sys.argv) > 3 else 28.0  # 28 km/h para deslocamento rápido pelas ruas
    run_loop(route_name=r_name, walk_speed_kmh=w_spd, transit_speed_kmh=t_spd)
