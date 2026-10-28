#!/usr/bin/env python3
import json
import math
import random
import sys
import time
import zmq

PORT = 17878

# Coordenada atual onde você está
START_LAT = -9.977835
START_LON = -67.825947

# Grade de quarteirões e ruas reais da região residencial (Acre / Rio Branco)
# Criando 30 waypoints interligados em circuito fechado (ruas e avenidas locais)
# delta_lat: ~0.0009 = ~100m, delta_lon: ~0.0009 = ~100m
WAYPOINTS = [
    (-9.977835, -67.825947), # 0: Início
    (-9.977200, -67.825900), # 1: Norte pela rua principal
    (-9.976500, -67.825850), # 2: Cruzamento norte
    (-9.976520, -67.825100), # 3: Virando a leste
    (-9.976540, -67.824300), # 4: Praça / Pokéstop próximo
    (-9.977100, -67.824250), # 5: Sul pelo quarteirão leste
    (-9.977800, -67.824200), # 6: Rua paralela ao sul
    (-9.978400, -67.824150), # 7: Esquina sul
    (-9.978380, -67.824850), # 8: Oeste retornando
    (-9.978350, -67.825950), # 9: Cruzamento sul
    (-9.978900, -67.825980), # 10: Extensão sul
    (-9.979400, -67.826000), # 11: Final da avenida
    (-9.979420, -67.826600), # 12: Oeste residencial
    (-9.978800, -67.826620), # 13: Subindo pelo quarteirão oeste
    (-9.978200, -67.826650), # 14: Meio da rua
    (-9.977500, -67.826700), # 15: Próximo à praça oeste
    (-9.976800, -67.826750), # 16: Esquina noroeste
    (-9.976200, -67.826800), # 17: Extensão noroeste
    (-9.976180, -67.826000), # 18: Leste rumo à avenida
    (-9.975500, -67.825950), # 19: Mais ao norte (centro do bairro)
    (-9.975480, -67.825200), # 20: Quarteirão nordeste
    (-9.975450, -67.824500), # 21: Perto de pokéstops
    (-9.976000, -67.824450), # 22: Sul
    (-9.976600, -67.824400), # 23: Retorno intermediário
    (-9.977300, -67.824900), # 24: Diagonal suave
    (-9.977900, -67.825300), # 25: Aproximação
    (-9.978400, -67.825600), # 26: Esquina sul 2
    (-9.978100, -67.826200), # 27: Oeste 2
    (-9.977400, -67.826150), # 28: Norte 2
    (-9.977835, -67.825947), # 29: Fechamento de ciclo perfeito!
]

def distance_meters(lat1, lon1, lat2, lon2):
    R = 6371000 # metros
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def run_loop():
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, 1500)
    sock.setsockopt(zmq.SNDTIMEO, 1500)
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(f"tcp://127.0.0.1:{PORT}")

    print(f"[WalkLoop] Iniciando circuito seguro de 30 waypoints a 1.2 m/s...")
    print(f"[WalkLoop] Conectado em tcp://127.0.0.1:{PORT}")

    speed_mps = 1.2 # ~4.3 km/h (velocidade ideal de caminhada humana, choca ovos e pega doces)
    step_time = 0.8 # intervalo de atualização em segundos
    step_dist = speed_mps * step_time # ~0.96 metros por passo

    loop_count = 0
    while True:
        loop_count += 1
        print(f"\n--- Iniciando Volta #{loop_count} do Circuito ---")
        for i in range(len(WAYPOINTS) - 1):
            p1 = WAYPOINTS[i]
            p2 = WAYPOINTS[i+1]
            total_dist = distance_meters(p1[0], p1[1], p2[0], p2[1])
            steps = max(1, int(total_dist / step_dist))

            print(f"Trecho {i+1}/{len(WAYPOINTS)-1}: {total_dist:.1f}m ({steps} passos)")

            for s in range(steps + 1):
                fraction = s / steps
                # Interpolação com micro-variação natural humana (jitter < 0.2m)
                jitter_lat = (random.random() - 0.5) * 0.000003
                jitter_lon = (random.random() - 0.5) * 0.000003
                cur_lat = p1[0] + (p2[0] - p1[0]) * fraction + jitter_lat
                cur_lon = p1[1] + (p2[1] - p1[1]) * fraction + jitter_lon

                payload = json.dumps({
                    "Action": "SendPosition",
                    "data": {"Lat": cur_lat, "Lng": cur_lon}
                })

                try:
                    sock.send_string(payload)
                    _ = sock.recv_string()
                except Exception as e:
                    # Se falhar ou timeout, recria socket
                    sock.close()
                    sock = ctx.socket(zmq.REQ)
                    sock.setsockopt(zmq.RCVTIMEO, 1500)
                    sock.setsockopt(zmq.SNDTIMEO, 1500)
                    sock.setsockopt(zmq.LINGER, 0)
                    sock.connect(f"tcp://127.0.0.1:{PORT}")

                time.sleep(step_time)

if __name__ == "__main__":
    run_loop()
