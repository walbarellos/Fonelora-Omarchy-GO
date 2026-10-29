#!/usr/bin/env python3
"""Fonelora PoGo Link — cliente ZeroMQ robusto para o plugin hook (porta 7878/7979).

Protocolo do plugin (RE via case pogo-hookbot):
  - REQ/REP tcp://127.0.0.1:17878 -> tcp://*:7878  (forward via adb)
      requisição: {"Action": "<nome>", "data": {...}}
      resposta:   {"State": <int>, "Action": "<nome>", ...}
  - PUB tcp://*:7979 -> keepalive {"Action":"KeepAlive"} a cada ~3s

Cuidados implementados:
  - socket REQ é uma máquina de estados: se o recv estoura timeout, o socket
    fica irrecuperável (EFSM). Por isso: timeout => destrói e recria.
  - reconexão automática + re-forward adb.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import zmq

DEVICE_PORT = 7878
LOCAL_PORT = 17878
KEEPALIVE_DEVICE_PORT = 7979
KEEPALIVE_LOCAL_PORT = 17979


def find_adb() -> str:
    env_adb = os.environ.get("ADB")
    if env_adb and Path_isfile(env_adb):
        return env_adb
    sdk_adb = os.path.expanduser("~/Android/Sdk/platform-tools/adb")
    if os.path.isfile(sdk_adb):
        return sdk_adb
    return shutil.which("adb") or "adb"


def Path_isfile(p: str) -> bool:
    return os.path.isfile(p)


class PogoLink:
    """Cliente REQ para o plugin com keepalive SUB e auto-healing."""

    def __init__(self, serial: str | None = None, local_port: int = LOCAL_PORT):
        self.adb = find_adb()
        self.serial = serial
        self.local_port = local_port
        self._ctx = zmq.Context.instance()
        self._sock: zmq.Socket | None = None
        self._lock = threading.Lock()
        self._last_keepalive: float = 0.0
        self._keepalive_thread: threading.Thread | None = None
        self._keepalive_stop = threading.Event()

    # ---------- infra ----------
    def _run_adb(self, args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
        cmd = [self.adb]
        if self.serial:
            cmd += ["-s", self.serial]
        return subprocess.run(cmd + args, capture_output=True, text=True, timeout=timeout)

    def ensure_forward(self) -> bool:
        r = self._run_adb(
            ["forward", f"tcp:{self.local_port}", f"tcp:{DEVICE_PORT}"]
        )
        return r.returncode == 0

    def ensure_keepalive_forward(self) -> bool:
        r = self._run_adb(
            ["forward", f"tcp:{KEEPALIVE_LOCAL_PORT}", f"tcp:{KEEPALIVE_DEVICE_PORT}"]
        )
        return r.returncode == 0

    def _new_socket(self, timeout_ms: int) -> zmq.Socket:
        s = self._ctx.socket(zmq.REQ)
        s.setsockopt(zmq.LINGER, 0)
        s.setsockopt(zmq.RCVTIMEO, timeout_ms)
        s.setsockopt(zmq.SNDTIMEO, timeout_ms)
        s.connect(f"tcp://127.0.0.1:{self.local_port}")
        return s

    def _close_socket(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close(0)
            except Exception:
                pass
            self._sock = None

    # ---------- request ----------
    def request(self, action: str, data: dict | None = None,
                timeout_ms: int = 2500, retries: int = 2) -> dict | None:
        """Envia uma ação e retorna a resposta dict, ou None em falha."""
        payload = {"Action": action}
        if data is not None:
            payload["data"] = data
        msg = json.dumps(payload)

        with self._lock:
            for attempt in range(retries + 1):
                try:
                    if self._sock is None:
                        self.ensure_forward()
                        self._sock = self._new_socket(timeout_ms)
                    self._sock.send_string(msg)
                    raw = self._sock.recv_string()
                    return json.loads(raw)
                except zmq.Again:
                    # timeout: socket REQ corrompido (falta de reply) => recriar
                    self._close_socket()
                    self.ensure_forward()
                except zmq.ZMQError:
                    self._close_socket()
                except Exception:
                    self._close_socket()
                    return None
                time.sleep(0.05 * (attempt + 1))
        return None

    @property
    def alive(self) -> bool:
        """True se o keepalive do plugin foi visto nos últimos ~10s."""
        return (time.time() - self._last_keepalive) < 10.0

    # ---------- keepalive ----------
    def start_keepalive_monitor(self) -> None:
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            return
        self._keepalive_stop.clear()

        def _watch():
            self.ensure_keepalive_forward()
            sub = self._ctx.socket(zmq.SUB)
            sub.setsockopt(zmq.LINGER, 0)
            sub.setsockopt_string(zmq.SUBSCRIBE, "")
            sub.setsockopt(zmq.RCVTIMEO, 2000)
            sub.connect(f"tcp://127.0.0.1:{KEEPALIVE_LOCAL_PORT}")
            last_forward = 0.0
            while not self._keepalive_stop.is_set():
                try:
                    _ = sub.recv_string()
                    self._last_keepalive = time.time()
                except zmq.ZMQError:
                    # re-forward periodicamente (adb derruba forwards às vezes)
                    if time.time() - last_forward > 30:
                        try:
                            self.ensure_keepalive_forward()
                        except Exception:
                            pass
                        last_forward = time.time()
                except Exception:
                    break
            sub.close(0)

        self._keepalive_thread = threading.Thread(target=_watch, daemon=True, name="pogo-keepalive")
        self._keepalive_thread.start()

    def stop(self) -> None:
        self._keepalive_stop.set()
        self._close_socket()

    # ---------- ações known ----------
    def current_position(self) -> tuple[float, float] | None:
        r = self.request("CurrentPosition")
        if r and r.get("State") == 200 and "data" in r:
            try:
                lat = float(r["data"]["Lat"])
                lon = float(r["data"]["Lng"])
                if lat or lon:
                    return (lat, lon)
            except Exception:
                pass
        return None

    def send_position(self, lat: float, lon: float) -> bool:
        r = self.request("SendPosition", {"Lat": lat, "Lng": lon})
        return bool(r and r.get("State") == 200)

    def state_check(self) -> dict | None:
        return self.request("StateCheck")

    def device_info(self) -> dict | None:
        return self.request("DeviceInfo")


if __name__ == "__main__":
    # Smoke test: CurrentPosition + StateCheck + keepalive
    link = PogoLink()
    link.start_keepalive_monitor()
    time.sleep(4.0)
    print("keepalive alivo:", link.alive)
    print("posicao:", link.current_position())
    print("state:", link.state_check())
    print("device:", link.device_info())
    link.stop()
