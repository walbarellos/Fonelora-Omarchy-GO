#!/usr/bin/env python3
"""
Fonelora Linux (Omarchy Edition) — Native Linux Backend for Fonelora Android GPS Changer
Reverse-engineered via REA from:
  - Fonelora Location Changer.exe (.NET Reactor / WPF / WebView2)
  - AndroidDevice.dll & MapService.dll
  - resource/gpslocate.apk (com.fonelora.alcassistant / SocketLocationService TCP:38438)
  - leafletMap/ (WebViewBridge & mapControl)
"""

import json
import os
import random
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
APK_PATH = BASE_DIR / "gpslocate.apk"
PACKAGE_NAME = "com.fonelora.alcassistant"
MAIN_ACTIVITY = "com.fonelora.alcassistant/.MainActivity"
SOCKET_SERVICE = "com.fonelora.alcassistant/.SocketLocationService"
DEVICE_PORT = 38438
LOCAL_PORT = 38438
POGO_DEVICE_PORT = 7878
POGO_LOCAL_PORT = 17878
HTTP_PORT = int(os.environ.get("FONELORA_HTTP_PORT", "18438"))


def find_adb() -> str:
    env_adb = os.environ.get("ADB")
    if env_adb and Path(env_adb).is_file():
        return env_adb
    sdk_adb = Path.home() / "Android/Sdk/platform-tools/adb"
    if sdk_adb.is_file():
        return str(sdk_adb)
    which_adb = shutil.which("adb")
    if which_adb:
        return which_adb
    proton_adb = (
        Path.home()
        / ".local/share/fonelora/pfx/drive_c/Program Files (x86)/Fonelora/Fonelora Location Changer/adb.exe"
    )
    if proton_adb.is_file():
        return str(proton_adb)
    return "adb"


ADB_BIN = find_adb()


class AndroidLocationController:
    """Manages ADB connection and persistent TCP socket to com.fonelora.alcassistant (port 38438)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sock: socket.socket | None = None
        self.sock_file = None
        self.selected_serial: str | None = None
        self.current_lat: float = -9.975487
        self.current_lon: float = -67.821538
        self.is_mocking: bool = False
        self.last_error: str | None = None
        self.device_model: str | None = None

    def _run_adb(self, args: list[str], serial: str | None = None, timeout: float = 15.0) -> subprocess.CompletedProcess:
        cmd = [ADB_BIN]
        target = serial or self.selected_serial
        if target:
            cmd.extend(["-s", target])
        cmd.extend(args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def list_devices(self) -> list[dict]:
        try:
            res = subprocess.run([ADB_BIN, "devices", "-l"], capture_output=True, text=True, timeout=8.0)
            devices = []
            for line in res.stdout.splitlines()[1:]:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    serial = parts[0]
                    state = parts[1]
                    model = serial
                    for p in parts[2:]:
                        if p.startswith("model:"):
                            model = p.split(":", 1)[1]
                    devices.append({"serial": serial, "state": state, "model": model})
            online = [d for d in devices if d["state"] == "device"]
            if online and (not self.selected_serial or self.selected_serial not in [d["serial"] for d in online]):
                self.selected_serial = online[0]["serial"]
                self.device_model = online[0]["model"]
            return devices
        except Exception as e:
            self.last_error = str(e)
            return []

    def ensure_apk_and_service(self, serial: str | None = None) -> tuple[bool, str]:
        devices = self.list_devices()
        online = [d for d in devices if d["state"] == "device"]
        if not online:
            return False, "Nenhum dispositivo Android conectado/autorizado via ADB (verifique a Depuração USB)."

        target = serial or self.selected_serial or online[0]["serial"]
        self.selected_serial = target
        for d in online:
            if d["serial"] == target:
                self.device_model = d["model"]

        # 1. Check if com.fonelora.alcassistant is installed
        pkg_check = self._run_adb(["shell", "pm", "path", PACKAGE_NAME], serial=target)
        if "package:" not in pkg_check.stdout:
            if not APK_PATH.is_file():
                return False, f"APK oficial não encontrado em {APK_PATH}"
            inst = self._run_adb(["install", "-r", "-g", str(APK_PATH)], serial=target, timeout=60.0)
            if inst.returncode != 0:
                return False, f"Falha ao instalar gpslocate.apk: {inst.stderr or inst.stdout}"

        # 2. Grant location/notification permissions and Mock Location appops
        self._run_adb(["shell", "pm", "grant", PACKAGE_NAME, "android.permission.ACCESS_FINE_LOCATION"], serial=target)
        self._run_adb(["shell", "pm", "grant", PACKAGE_NAME, "android.permission.ACCESS_COARSE_LOCATION"], serial=target)
        self._run_adb(["shell", "pm", "grant", PACKAGE_NAME, "android.permission.POST_NOTIFICATIONS"], serial=target)
        appops = self._run_adb(["shell", "appops", "set", PACKAGE_NAME, "android:mock_location", "allow"], serial=target)

        # 3. Start MainActivity and SocketLocationService if not already listening
        pid_res = self._run_adb(["shell", "pidof", PACKAGE_NAME], serial=target)
        if not pid_res.stdout.strip():
            self._run_adb(["shell", "am", "start", "-n", MAIN_ACTIVITY, "-f", "0x20000000"], serial=target)
            time.sleep(0.6)

        self._run_adb(["shell", "am", "start-foreground-service", "-n", SOCKET_SERVICE], serial=target)
        self._run_adb(["shell", "am", "startservice", "-n", SOCKET_SERVICE], serial=target)

        # 4. Forward TCP 38438 -> 38438
        fwd = self._run_adb(["forward", f"tcp:{LOCAL_PORT}", f"tcp:{DEVICE_PORT}"], serial=target)
        if fwd.returncode != 0:
            return False, f"Falha no adb forward: {fwd.stderr or fwd.stdout}"

        return True, f"Conectado ao Android ({self.device_model or target}) na porta {LOCAL_PORT}"

    def _connect_socket_locked(self) -> tuple[bool, str]:
        if self.sock is not None:
            return True, "OK"

        ok, msg = self.ensure_apk_and_service()
        if not ok:
            return False, msg

        # Try connecting to 127.0.0.1:38438 (retry briefly while service starts)
        last_err = ""
        for attempt in range(5):
            try:
                s = socket.create_connection(("127.0.0.1", LOCAL_PORT), timeout=2.5)
                s.settimeout(3.0)
                f = s.makefile("rw", encoding="utf-8", newline="\n")
                # Test or keep connection ready
                self.sock = s
                self.sock_file = f
                return True, "Socket conectado"
            except Exception as e:
                last_err = str(e)
                self._close_socket_locked()
                self._run_adb(["shell", "am", "start", "-n", MAIN_ACTIVITY, "-f", "0x20000000"])
                self._run_adb(["shell", "am", "startservice", "-n", SOCKET_SERVICE])
                time.sleep(0.4)

        return False, f"Não foi possível conectar ao SocketLocationService (38438): {last_err}"

    def _close_socket_locked(self) -> None:
        if self.sock_file:
            try:
                self.sock_file.close()
            except Exception:
                pass
            self.sock_file = None
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def send_location(self, lat: float, lon: float) -> tuple[bool, str]:
        with self.lock:
            # Assinatura com ruído estocástico (Jitter físico de satélite civil GPS: ±0.4m a ±1.2m)
            # Utiliza nanossegundos do timer do sistema como seed adicional
            ns_seed = time.time_ns() % 1000000
            random.seed(time.time() + (ns_seed / 1e9))
            
            jitter_lat = (random.random() - 0.5) * 0.000010
            jitter_lon = (random.random() - 0.5) * 0.000010
            
            self.current_lat = round(float(lat) + jitter_lat, 7)
            self.current_lon = round(float(lon) + jitter_lon, 7)

            # 1. First attempt direct Pokémon GO ZeroMQ injection (Port 7878 / 17878)
            pogo_ok = self._send_pogo_zmq(self.current_lat, self.current_lon)
            if pogo_ok:
                self.is_mocking = True
                self.last_error = None
                return True, "OK (Injetado via Pokémon GO ZMQ)"

            # 2. Fallback to standard mock assistant (Port 38438) for other apps
            for attempt in range(2):
                ok, msg = self._connect_socket_locked()
                if not ok:
                    self.last_error = msg
                    return False, msg
                try:
                    assert self.sock_file is not None
                    self.sock_file.write(f"{self.current_lat:.7f},{self.current_lon:.7f}\n")
                    self.sock_file.flush()
                    reply = self.sock_file.readline().strip()
                    if reply == "OK":
                        self.is_mocking = True
                        self.last_error = None
                        return True, "OK"
                    elif reply:
                        self.last_error = f"Resposta inesperada do serviço: {reply}"
                        self._close_socket_locked()
                    else:
                        # EOF: service closed socket, restart service and retry once
                        self._close_socket_locked()
                        self._run_adb(["shell", "am", "startservice", "-n", SOCKET_SERVICE])
                        time.sleep(0.3)
                except Exception as e:
                    self._close_socket_locked()
                    self.last_error = str(e)
                    time.sleep(0.2)

            return False, self.last_error or "Falha ao enviar coordenadas ao Android"

    def get_pogo_position(self) -> tuple[float, float] | None:
        """Consulta onde o avatar está agora no jogo via ZMQ (Single Source of Truth)."""
        try:
            import zmq
            self._run_adb(["forward", f"tcp:{POGO_LOCAL_PORT}", f"tcp:{POGO_DEVICE_PORT}"])
            ctx = zmq.Context.instance()
            sock = ctx.socket(zmq.REQ)
            sock.setsockopt(zmq.RCVTIMEO, 1000)
            sock.setsockopt(zmq.SNDTIMEO, 1000)
            sock.setsockopt(zmq.LINGER, 0)
            sock.connect(f"tcp://127.0.0.1:{POGO_LOCAL_PORT}")
            sock.send_string(json.dumps({"Action": "CurrentPosition"}))
            raw = sock.recv_string()
            sock.close()
            data = json.loads(raw)
            if data.get("State") == 200 and "data" in data:
                lat = float(data["data"]["Lat"])
                lng = float(data["data"]["Lng"])
                if lat != 0.0 and lng != 0.0:
                    self.current_lat = lat
                    self.current_lon = lng
                    return (lat, lng)
        except Exception:
            pass
        return None

    def _send_pogo_zmq(self, lat: float, lon: float) -> bool:
        """Attempts injecting location into Pokémon GO via custom ZeroMQ interface (tcp://*:7878)."""
        try:
            import zmq
        except ImportError:
            return False

        try:
            self._run_adb(["forward", f"tcp:{POGO_LOCAL_PORT}", f"tcp:{POGO_DEVICE_PORT}"])
            ctx = zmq.Context.instance()
            sock = ctx.socket(zmq.REQ)
            sock.setsockopt(zmq.RCVTIMEO, 800)
            sock.setsockopt(zmq.SNDTIMEO, 800)
            sock.setsockopt(zmq.LINGER, 0)
            sock.connect(f"tcp://127.0.0.1:{POGO_LOCAL_PORT}")

            payload = json.dumps({"Action": "SendPosition", "data": {"Lat": float(lat), "Lng": float(lon)}})
            sock.send_string(payload)
            reply = sock.recv_string()
            sock.close()
            data = json.loads(reply)
            return data.get("State") == 200 or data.get("Action") == "SendPosition"
        except Exception:
            return False

    def stop_mocking(self) -> tuple[bool, str]:
        with self.lock:
            try:
                if self.sock_file is not None:
                    self.sock_file.write("stop\n")
                    self.sock_file.flush()
                    _ = self.sock_file.readline()
            except Exception:
                pass
            finally:
                self._close_socket_locked()
            self._run_adb(["shell", "am", "force-stop", PACKAGE_NAME])
            self.is_mocking = False
            return True, "Simulação de GPS encerrada e localização restaurada."


controller = AndroidLocationController()


class BotManager:
    """Gerencia o subprocesso do bot_brain.py (start/stop) e expõe o estado.

    O bot_brain publica seu estado rico em .bot_brain_state.json; o server só
    repassa para o /api/bot e controla o processo via SIGTERM (graceful — o
    bot limpa .bot_pause e publica phase=stopped na saída).
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.log_path = BASE_DIR / "bot_web.log"

    def is_running(self) -> bool:
        with self.lock:
            return self.proc is not None and self.proc.poll() is None

    def _tail_log(self, n: int = 40) -> list[str]:
        try:
            if self.log_path.is_file():
                lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                return lines[-n:]
        except Exception:
            pass
        return []

    def state(self) -> dict:
        brain = {}
        state_file = BASE_DIR / ".bot_brain_state.json"
        if state_file.is_file():
            try:
                brain = json.loads(state_file.read_text(encoding="utf-8"))
                # expira estado velho (>15s => processo morto sem limpar)
                if time.time() - brain.get("timestamp", 0) > 15:
                    brain["running"] = False
                    if brain.get("phase") not in ("stopped",):
                        brain["phase"] = "stopped"
            except Exception:
                pass
        brain["processRunning"] = self.is_running()
        return brain

    def start(self, solo: bool = False) -> tuple[bool, str]:
        with self.lock:
            if self.proc is not None and self.proc.poll() is None:
                return False, "Bot já está em execução."
            brain_py = BASE_DIR / "bot_brain.py"
            if not brain_py.is_file():
                return False, "bot_brain.py não encontrado."
            py = BASE_DIR / ".venv/bin/python3"
            cmd = [str(py) if py.is_file() else sys.executable, str(brain_py)]
            if solo:
                cmd.append("--solo")
            out = self.log_path.open("a", encoding="utf-8")
            out.write(f"\n=== bot iniciado {time.strftime('%Y-%m-%d %H:%M:%S')} (solo={solo}) ===\n")
            out.flush()
            try:
                self.proc = subprocess.Popen(cmd, cwd=str(BASE_DIR), stdout=out,
                                             stderr=subprocess.STDOUT, text=True)
            except Exception as e:
                out.close()
                return False, f"Falha ao iniciar bot: {e}"
            return True, f"Bot iniciado (PID {self.proc.pid})."

    def stop(self) -> tuple[bool, str]:
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                return False, "Bot não está em execução."
            pid = self.proc.pid
            try:
                self.proc.terminate()  # SIGTERM => KeyboardInterrupt no bot
            except Exception as e:
                return False, f"Falha ao sinalizar bot: {e}"
            return True, f"Bot sinalizado para parar (PID {pid})."

    def save_config(self, patch: dict) -> tuple[bool, str]:
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            return False, f"bot_config.json ilegível: {e}"
        # aplica só chaves de política conhecidas (whitelist — evita poluir)
        allowed_top = {"inventory", "hunt", "restock", "evolve"}
        for k, v in (patch or {}).items():
            if k in allowed_top and isinstance(v, dict):
                cfg.setdefault(k, {}).update(v)
        try:
            CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
            return True, "Configuração do bot salva."
        except Exception as e:
            return False, f"Falha ao salvar config: {e}"


CONFIG_FILE = BASE_DIR / "bot_config.json"
bot_manager = BotManager()


class FoneloraHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass

    def _send_json(self, data: dict, status: int = 200) -> None:
        raw = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            devices = controller.list_devices()
            # Sempre consulta a posição real viva do jogo antes de responder
            controller.get_pogo_position()

            bot_state = {}
            state_file = BASE_DIR / ".bot_state.json"
            if state_file.is_file():
                try:
                    bot_state = json.loads(state_file.read_text(encoding="utf-8"))
                    # Expirar estado se mais velho que 30s
                    if time.time() - bot_state.get("timestamp", 0) > 30:
                        bot_state = {"state": "idle", "details": "Script parado"}
                except Exception:
                    pass

            self._send_json(
                {
                    "ok": True,
                    "adb_path": ADB_BIN,
                    "devices": devices,
                    "selected_serial": controller.selected_serial,
                    "device_model": controller.device_model,
                    "is_mocking": controller.is_mocking,
                    "lat": controller.current_lat,
                    "lon": controller.current_lon,
                    "last_error": controller.last_error,
                    "bot_state": bot_state,
                }
            )
            return

        if parsed.path == "/api/bot":
            cfg = {}
            if CONFIG_FILE.is_file():
                try:
                    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                except Exception:
                    pass
            self._send_json({"ok": True, "bot": bot_manager.state(), "config": cfg})
            return

        if parsed.path == "/api/routes":
            routes_file = BASE_DIR / "routes_data.json"
            if routes_file.is_file():
                routes_data = json.loads(routes_file.read_text(encoding="utf-8"))
            else:
                routes_data = {}
            self._send_json({"ok": True, "routes": routes_data})
            return

        if parsed.path in ("/", "/index.html"):
            index_file = BASE_DIR / "index.html"
            content = index_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}

        if parsed.path == "/api/connect":
            serial = body.get("serial")
            # If Pokemon GO is installed, do NOT install gpslocate.apk or register mock providers!
            devices = controller.list_devices()
            online = [d for d in devices if d["state"] == "device"]
            target = serial or controller.selected_serial or (online[0]["serial"] if online else None)
            if target:
                controller.selected_serial = target
                # Set up port forwarding for Pokémon GO ZeroMQ (7878)
                controller._run_adb(["forward", f"tcp:{POGO_LOCAL_PORT}", f"tcp:{POGO_DEVICE_PORT}"], serial=target)
                self._send_json({"ok": True, "message": f"Conectado ao Android ({target}) via canal Pokémon GO (7878)", "devices": controller.list_devices()})
            else:
                self._send_json({"ok": False, "message": "Nenhum dispositivo encontrado", "devices": []})
            return

        if parsed.path == "/api/location":
            lat = float(body["lat"])
            lon = float(body["lon"])
            ok, msg = controller.send_location(lat, lon)
            self._send_json(
                {
                    "ok": ok,
                    "message": msg,
                    "lat": controller.current_lat,
                    "lon": controller.current_lon,
                    "is_mocking": controller.is_mocking,
                }
            )
            return

        if parsed.path == "/api/stop":
            ok, msg = controller.stop_mocking()
            self._send_json({"ok": ok, "message": msg, "is_mocking": False})
            return

        if parsed.path == "/api/bot/start":
            solo = bool(body.get("solo", False))
            ok, msg = bot_manager.start(solo=solo)
            self._send_json({"ok": ok, "message": msg})
            return

        if parsed.path == "/api/bot/stop":
            ok, msg = bot_manager.stop()
            self._send_json({"ok": ok, "message": msg})
            return

        if parsed.path == "/api/bot/config":
            ok, msg = bot_manager.save_config(body.get("config", body))
            self._send_json({"ok": ok, "message": msg})
            return

        if parsed.path == "/api/wifi-connect":
            addr = str(body.get("address", "")).strip()
            if not addr:
                self._send_json({"ok": False, "message": "Informe o IP:Porta do Android"}, status=400)
                return
            res = subprocess.run([ADB_BIN, "connect", addr], capture_output=True, text=True, timeout=10.0)
            ok = "connected to" in res.stdout.lower()
            self._send_json({"ok": ok, "message": (res.stdout + res.stderr).strip(), "devices": controller.list_devices()})
            return

        self.send_error(404)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), FoneloraHTTPHandler)
    print(f"[Fonelora Omarchy] Servidor iniciado em http://127.0.0.1:{HTTP_PORT}")
    print(f"[Fonelora Omarchy] ADB detectado: {ADB_BIN}")
    print(f"[Fonelora Omarchy] APK Android:   {APK_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
