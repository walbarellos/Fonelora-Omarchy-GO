#!/usr/bin/env python3
"""Fonelora Bot Brain v2 — orquestrador com malha de fingerprints temporais.

Princípios (case pogo-hookbot):
  1. O hooking il2cpp ELIMINA a automação de UI: cada ação é UMA chamada de
     método no processo do jogo. Mas o servidor telemetra ritmo humano, então
     cada fluxo de UI que um HUMANO faria vira um TEMPLATE DE TIMING com
     passos fingerprintados — o bot "gasta o tempo" que gastaria naquelas telas.
  2. Malha 4D de fingerprints: todo delay = f(grupo, fluxo, passo, sequência),
     quantizado em ns por grupo. Nem em loop infinito dois delays se repetem.
  3. Cada grupo tem sua própria distribuição (lognormal params), quantum de ns,
     fadiga, hesitações e rajadas — assinaturas distintas entre grupos.
  4. Scheduler Markoviano com cooldowns (nunca escolha uniforme aleatória).
  5. Modo sombra: ação ZMQ ainda inexistente no plugin => o passo queima seu
     tempo humano e loga; quando a extensão nativa entrar, acende sem mudar código.

Fluxos modelados (UI virtual → template de timing):
  G1 encontro:     abordar → abrir encontro → avaliar → N arremessos → resultado
  G2 giro:         selecionar stop → caminhar → abrir → girar → coletar → fechar
  G3 descarte:     pokébola → mochila → aba itens → lixeira → selecionar →
                   N toques no "+" → yes → fechar
  G4 evolução:     pokébola → treinadores → filtrar → evoluir (animação) →
                   favoritar → fechar
  G5 ócio:         micro-telas: câmera, avatar, buddy, zoom, menu

Uso:
  python3 bot_brain.py            # attached: interage; pausa walk_loop via .bot_pause
  python3 bot_brain.py --solo     # o cérebro também comanda o movimento
  python3 bot_brain.py --probe    # só sonda ações ZMQ do plugin
  python3 bot_brain.py --list-mesh  # imprime a malha de fluxos/passo e sai
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import secrets
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_venv = Path(__file__).resolve().parent / ".venv/bin/python3"
if _venv.is_file() and sys.executable != str(_venv):
    os.execv(str(_venv), [str(_venv)] + sys.argv)

from pogolink import PogoLink  # noqa: E402

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "bot_config.json"
PAUSE_FILE = BASE / ".bot_pause"
NS = 1_000_000_000
BRAIN_STATE_FILE = BASE / ".bot_brain_state.json"

# Mapeamento nome→id enum Holoholo.Rpc.Item (pins 0.433.1). Usado só para
# amostrar o inventário via CurrentInventory (IItemBag.GetItemCount), que
# aceita o id inteiro. Os itens AUSENTES de keep_max nunca são tocados.
ITEM_NAME_TO_ID = {
    "ITEM_POKE_BALL": 1, "ITEM_GREAT_BALL": 2, "ITEM_ULTRA_BALL": 3,
    "ITEM_MASTER_BALL": 4,
    "ITEM_POTION": 101, "ITEM_SUPER_POTION": 102, "ITEM_HYPER_POTION": 103,
    "ITEM_MAX_POTION": 104,
    "ITEM_REVIVE": 201, "ITEM_MAX_REVIVE": 202,
    "ITEM_RAZZ_BERRY": 501, "ITEM_NANAB_BERRY": 502, "ITEM_PINAP_BERRY": 503,
    "ITEM_SITRUS_BERRY": 504,
    "ITEM_X_ATTACK": 701, "ITEM_X_DEFENSE": 702, "ITEM_X_MIRACLE": 705,
    "ITEM_SPECIAL_ATTACK": 710,
}

# Fase de UI por grupo (copy do painel da página)
GROUP_PHASE = {"G1": "hunting", "G2": "restocking", "G3": "inventory",
               "G4": "evolving", "G5": "idle"}


def _seed_int(*parts) -> int:
    """Seed determinística e suportada (int) a partir de componentes arbitrários.

    Python 3.11+ rejeita seeds em tupla/dict em random.Random(). Hashiamos os
    componentes (estável via sha1) para um int — determinístico dentro da
    sessão e entre reinícios, e mantém a malha 4D (grupo, fluxo, passo, seq)
    sem repetir nem em loop infinito.
    """
    key = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha1(key).digest()[:8], "big")


class Telemetry:
    """Publica estado rico do bot em .bot_brain_state.json (lido por /api/bot).

    Cobertura de fases (o painel da página mapeia cada uma para copy):
      stopped / starting / waiting_game / probing / hunting / restocking /
      inventory / evolving / idle / walking / contemplando / error
    """

    MAX_LOG = 40

    def __init__(self, seed: int, config: dict):
        self.seed = seed
        self.config = config
        self.t0 = time.time()
        self.running = False
        self.phase = "stopped"
        self.group: str | None = None
        self.group_label: str | None = None
        self.flow: str | None = None
        self.step: str | None = None
        self.step_idx: int | None = None
        self.seq = 0
        self.stats: dict[str, int] = {}
        self.caps_available: list[str] = []
        self.caps_shadow: list[str] = []
        self.inventory: dict[str, int] = {}
        self.log_lines: list[str] = []
        self.last_action: dict | None = None
        self._last_write = 0.0

    # --- setters baratos (o write é throttled) ---
    def set_phase(self, phase: str) -> None:
        self.phase = phase

    def set_group(self, name: str | None, label: str | None = None) -> None:
        self.group, self.group_label = name, label

    def set_flow(self, flow: str | None) -> None:
        self.flow = flow

    def set_step(self, label: str | None, idx: int | None = None) -> None:
        self.step, self.step_idx = label, idx

    def note_action(self, action: str, state) -> None:
        self.last_action = {"action": action, "state": state, "at": time.time()}

    def count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    def log(self, line: str) -> None:
        self.log_lines.append(line)
        if len(self.log_lines) > self.MAX_LOG:
            self.log_lines = self.log_lines[-self.MAX_LOG:]

    def write(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_write < 0.4:
            return
        self._last_write = now
        inv_cfg = self.config.get("inventory", {})
        hunt = self.config.get("hunt", {})
        evo = self.config.get("evolve", {})
        payload = {
            "running": self.running,
            "phase": self.phase,
            "group": self.group,
            "groupLabel": self.group_label,
            "flow": self.flow,
            "step": self.step,
            "stepIdx": self.step_idx,
            "seq": self.seq,
            "stats": self.stats,
            "inventory": self.inventory,
            "keepMax": inv_cfg.get("keep_max", {}),
            "capabilities": {"available": self.caps_available,
                             "shadow": self.caps_shadow},
            "thresholds": {
                "cpStrong": hunt.get("cp_strong"),
                "cpFlee": hunt.get("cp_flee"),
                "ivFlee": hunt.get("iv_flee"),
                "minIv": evo.get("min_iv"),
                "favoriteIv": evo.get("favorite_iv"),
            },
            "log": self.log_lines,
            "seed": self.seed,
            "uptimeS": round(now - self.t0, 1),
            "lastAction": self.last_action,
            "timestamp": now,
        }
        try:
            tmp = BRAIN_STATE_FILE.with_name(BRAIN_STATE_FILE.name + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(BRAIN_STATE_FILE)
        except Exception:
            pass


# ───────────────────────── malha de timing ─────────────────────────

@dataclass(frozen=True)
class TimingProfile:
    """Assinatura temporal de um grupo (distribuição, quantum, fadiga)."""
    name: str
    quantum_ns: int      # tique único por grupo — separa grupos em µs
    offset_ns: int       # deslocamento base único
    mu: float            # lognormal log-média do intervalo entre passos (s)
    sigma: float         # dispersão (cauda pesada humana)
    burst_prob: float    # prob. de reflexo rápido (rajada)
    burst_factor: float
    hesitate_prob: float # prob. de pausa de "pensamento"
    hesitate_range: tuple[float, float]
    drift_per_hour: float  # fadiga de sessão


def mesh_delay_ns(profile: TimingProfile, rng: random.Random,
                  flow_id: str, step_idx: int, seq: int,
                  bias: tuple[float, float], session_s: float) -> int:
    """Malha 4D: (grupo→profile, fluxo, passo, sequência) => delay ns único."""
    base = rng.lognormvariate(profile.mu, profile.sigma)
    base *= rng.uniform(*bias)                     # caráter do passo dentro do fluxo
    base *= 1.0 + profile.drift_per_hour * (session_s / 3600.0)
    if rng.random() < profile.burst_prob:
        base *= profile.burst_factor
    if rng.random() < profile.hesitate_prob:
        base += rng.uniform(*profile.hesitate_range)

    # hash posicional: (fluxo, passo, seq) → tique único no quantum do grupo
    h = (abs(hash((flow_id, step_idx, seq))) % profile.quantum_ns)
    ns = (int(base * NS) // profile.quantum_ns) * profile.quantum_ns + profile.offset_ns + h
    return max(profile.quantum_ns, ns)


# ───────────────────────── capacidades ────────────────────────────

class CapabilityRegistry:
    # NOTA: StopMockLocation NUNCA é sondado de propósito — ele desligaria o mock.
    KNOWN_NOW = ["CurrentPosition", "SendPosition", "StateCheck", "DeviceInfo",
                 "IsLocationMock"]
    # Ações da extensão nativa (WI-007/008): registradas no plugin via
    # GameBotActions.addExtraFunc. CurrentInventory e Status são probes de
    # saúde/resolução (il2cpp bind) — sem SendRpc.
    FUTURE = ["GetNearby", "StartEncounter", "GetEncounterState", "ThrowBall",
              "FleeEncounter", "OpenFort", "SpinFort", "GetInventory",
              "DropItem", "EvolvePokemon", "FavoritePokemon", "GetPlayerStats",
              "CurrentInventory", "Status"]

    def __init__(self, link: PogoLink):
        self.link = link
        self.available: set[str] = set()
        self.shadow: set[str] = set(self.FUTURE)

    def probe(self) -> None:
        for a in self.KNOWN_NOW:
            r = self.link.request(a, None, timeout_ms=1800)
            if r is not None and r.get("State") != 400:
                self.available.add(a)
        for a in self.FUTURE:
            r = self.link.request(a, {"probe": True}, timeout_ms=1500)
            if r is not None and r.get("State") != 400:
                self.available.add(a)
                self.shadow.discard(a)

    def has(self, action: str) -> bool:
        return action in self.available


# ───────────────────────── contexto ───────────────────────────────

@dataclass
class FlowStep:
    label: str
    action: str | None = None          # ação ZMQ (None = passo de "pensamento"/timing puro)
    payload: dict | Callable[[], dict] | None = None
    bias: tuple[float, float] = (0.75, 1.35)  # multiplicador de tempo deste passo


class BotContext:
    def __init__(self, link: PogoLink, caps: CapabilityRegistry,
                 config: dict, solo: bool, seed: int):
        self.link = link
        self.caps = caps
        self.config = config
        self.solo = solo
        self.seed = seed
        self.seq = 0
        self.stats: dict[str, int] = {}
        self.group = "SYS"
        self.profile: TimingProfile | None = None
        self.session_t0 = time.time()
        self.log_path = BASE / "bot_session.log"
        self.tel = Telemetry(seed, config)
        self.tel.caps_available = sorted(caps.available)
        self.tel.caps_shadow = sorted(caps.shadow)

    # --- logging/stats ---
    def log(self, tag: str, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} [{tag}] {msg}"
        print(line, flush=True)
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        self.tel.log(line)

    def count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n
        self.tel.count(key, n)

    # --- malha ---
    def step(self, flow_id: str, step_idx: int, step: FlowStep,
             quiet: bool = True) -> dict | None:
        """Executa um passo de fluxo: ação (ou sombra) + delay fingerprintado."""
        self.seq += 1
        rng = random.Random(_seed_int(self.seed, self.group, flow_id, step_idx, self.seq))
        session_s = time.time() - self.session_t0
        data = step.payload() if callable(step.payload) else step.payload
        result = None
        # publica o passo atual (o painel mostra "fazendo X")
        self.tel.seq = self.seq
        self.tel.set_flow(flow_id)
        self.tel.set_step(step.label, step_idx)
        if step.action and self.caps.has(step.action):
            r = self.link.request(step.action, data)
            result = r or {}
            self.tel.note_action(step.action, result.get("State", "timeout"))
            if not quiet:
                self.log(self.group, f"{flow_id}.{step.label} -> State={result.get('State', 'timeout')}")
        elif step.action:
            result = {"State": "shadow"}
            self.tel.note_action(step.action, "shadow")
        else:
            self.tel.note_action("(timing)", "humanized")
        ns = mesh_delay_ns(self.profile, rng, flow_id, step_idx, self.seq,
                           step.bias, session_s)
        time.sleep(ns / NS)
        self.tel.write()
        return result

    def steps(self, flow_id: str, steps: list[FlowStep], start: int = 0) -> None:
        for i, st in enumerate(steps, start=start):
            self.step(flow_id, i, st, quiet=False)

    # --- coordenação com walk_loop ---
    @contextmanager
    def park(self):
        """Pausa o walk_loop (.bot_pause) durante interações que exigem parada."""
        try:
            PAUSE_FILE.touch()
        except Exception:
            pass
        try:
            yield
        finally:
            try:
                PAUSE_FILE.unlink(missing_ok=True)
            except Exception:
                pass

    def walk_to(self, lat: float, lon: float, speed_kmh: float) -> None:
        self.tel.set_phase("walking")
        cur = self.link.current_position()
        if not cur:
            return
        dlat, dlon = lat - cur[0], lon - cur[1]
        dist = math.hypot(dlat * 111_000, dlon * 111_000 * math.cos(math.radians(lat)))
        step_m = max(speed_kmh / 3.6 * random.uniform(0.6, 0.9), 0.5)
        steps = max(1, min(int(dist / step_m), 500))
        for i in range(1, steps + 1):
            f = i / steps
            self.link.send_position(
                cur[0] + dlat * f + (random.random() - 0.5) * 0.000008,
                cur[1] + dlon * f + (random.random() - 0.5) * 0.000008)
            time.sleep(random.uniform(0.55, 0.95))
        # restaura a fase do grupo corrente após o deslocamento
        self.tel.set_phase(GROUP_PHASE.get(self.group, "idle"))

    def sample_inventory(self) -> None:
        """Lê as contagens atuais dos itens gerenciados (IItemBag.GetItemCount).

        Só consulta os itens presentes em keep_max — a mesma política de
        descarte. Itens fora de keep_max nunca são lidos nem tocados.
        """
        keep = self.config.get("inventory", {}).get("keep_max", {})
        inv: dict[str, int] = {}
        for name in keep:
            iid = ITEM_NAME_TO_ID.get(name)
            if iid is None:
                continue
            r = self.link.request("CurrentInventory", {"item": iid}, timeout_ms=1500)
            if r and r.get("State") == 200:
                try:
                    d = r.get("data")
                    cnt = d.get("count") if isinstance(d, dict) else None
                    if cnt is None and isinstance(d, str):
                        cnt = json.loads(d).get("count")
                    if cnt is not None:
                        inv[name] = int(cnt)
                except Exception:
                    pass
        if inv:
            self.tel.inventory = inv
            self.tel.write(force=True)


# ───────────────────────── grupos (fluxos) ────────────────────────

def g1_hunt(ctx: BotContext) -> None:
    cfg = ctx.config["hunt"]
    r = ctx.step("scan", 0, FlowStep("varrer spawns", "GetNearby",
                                      {"types": ["pokemon"], "limit": 12}), quiet=False)
    if not r or r.get("State") == "shadow":
        ctx.log("G1", "varredura indisponível (extensão pendente) — sombra")
        return
    spawns = (r.get("data", {}) or {}).get("pokemon", [])
    if not spawns:
        ctx.log("G1", "nenhum spawn no raio")
        return
    spawns.sort(key=lambda s: s.get("distance", 9999))
    seen = ctx.config.setdefault("seen", {})
    target = next((s for s in spawns
                   if str(s.get("pokemonId")) not in seen
                   or s.get("cp", 0) >= cfg["cp_strong"]), None)
    if not target:
        ctx.log("G1", "spawns presentes; nenhum atende política (novo/forte)")
        return

    flow = "encontro"
    with ctx.park():
        if ctx.solo:
            ctx.step(flow, 1, FlowStep("abordar a pé"))
            ctx.walk_to(target["lat"], target["lng"], cfg["approach_kmh"])
        ctx.step(flow, 2, FlowStep("tocar no spawn", "StartEncounter",
                                   {"encounterId": target.get("encounterId"),
                                    "pokemonId": target.get("pokemonId")}))
        st = ctx.step(flow, 3, FlowStep("analisar tela de encontro", "GetEncounterState"))
        data = (st or {}).get("data", {}) or {}
        cp = data.get("cp", 0)
        iv_pct = data.get("ivPct", (data.get("ivAtk", 0) + data.get("ivDef", 0)
                                    + data.get("ivSta", 0)) / 45 * 100)
        ctx.log("G1", f"alvo {target.get('pokemonId')} CP={cp} IV={iv_pct:.0f}%")
        seen[str(target.get("pokemonId"))] = True

        if cp < cfg["cp_flee"] and iv_pct < cfg["iv_flee"]:
            ctx.step(flow, 4, FlowStep("decidir fugir (botão fuga)"))
            ctx.step(flow, 5, FlowStep("tocar FUGIR", "FleeEncounter", {}))
            ctx.count("flees")
            return

        for i, ball in enumerate(cfg["ball_sequence"]):
            ctx.step(flow, 6 + i, FlowStep(
                f"arremesso {i + 1} ({ball})", "ThrowBall",
                {"ballType": ball, "razz": cp >= cfg["cp_strong"]},
                bias=(0.85, 1.6)))
            ctx.count("throws")
            chk = ctx.step(flow, 20 + i, FlowStep("aguardar resultado do arremesso",
                                                  "GetEncounterState"))
            if chk and (chk.get("data", {}) or {}).get("caught"):
                ctx.log("G1", "captura confirmada")
                ctx.count("catches")
                ctx.step(flow, 30, FlowStep("tela de recompensas"))
                return
        ctx.log("G1", "bolas esgotadas no encontro")
        ctx.step(flow, 40, FlowStep("sair do encontro", "FleeEncounter", {}))


def g2_restock(ctx: BotContext) -> None:
    cfg = ctx.config["restock"]
    r = ctx.step("giro", 0, FlowStep("procurar checkpoint", "GetNearby",
                                     {"types": ["fort"], "limit": 10}), quiet=False)
    if not r or r.get("State") == "shadow":
        ctx.log("G2", "giro indisponível (extensão pendente) — sombra")
        return
    forts = (r.get("data", {}) or {}).get("forts", [])
    spin = next((f for f in forts
                 if f.get("type") == "CHECKPOINT"
                 and f.get("distance", 9999) <= cfg["max_range_m"]
                 and not f.get("cooldown")), None)
    if not spin:
        ctx.log("G2", "sem checkpoint disponível")
        return
    flow = "giro"
    with ctx.park():
        if ctx.solo:
            ctx.step(flow, 1, FlowStep("caminhar até o stop"))
            ctx.walk_to(spin["lat"], spin["lng"], cfg["approach_kmh"])
        ctx.step(flow, 2, FlowStep("abrir Pokéstop", "OpenFort", {"fortId": spin["fortId"]}))
        ctx.step(flow, 3, FlowStep("girar o disco (arrasto circular)", "SpinFort",
                                   {"fortId": spin["fortId"], "spinDeg": random.uniform(0, 360)},
                                   bias=(0.9, 1.8)))
        ctx.count("spins")
        ctx.step(flow, 4, FlowStep("tela de itens coletados"))
        inv = ctx.step(flow, 5, FlowStep("conferir nível da mochila", "GetInventory"))
        if inv and inv.get("State") not in (400, "shadow"):
            items = (inv.get("data", {}) or {}).get("items", [])
            balls = sum(i.get("count", 0) for i in items
                        if i.get("itemId") in ("ITEM_POKE_BALL", "ITEM_GREAT_BALL", "ITEM_ULTRA_BALL"))
            ctx.log("G2", f"bolas na mochila: {balls}")
        ctx.step(flow, 6, FlowStep("fechar Pokéstop"))


def g3_inventory(ctx: BotContext) -> None:
    flow = "descarte"
    keep = ctx.config["inventory"]["keep_max"]
    with ctx.park():
        ctx.step(flow, 0, FlowStep("abrir menu pokébola", bias=(0.6, 1.1)))
        r = ctx.step(flow, 1, FlowStep("abrir mochila", "GetInventory"), quiet=False)
        if not r or r.get("State") == "shadow":
            ctx.log("G3", "inventário indisponível (extensão pendente) — sombra")
            ctx.step(flow, 2, FlowStep("fechar menu pokébola"))
            return
        items = (r.get("data", {}) or {}).get("items", [])
        step_i = 2
        for it in items:
            item_id, count = it.get("itemId"), it.get("count", 0)
            cap = keep.get(item_id)
            if cap is None or count <= cap:
                continue
            excess = count - cap
            ctx.step(flow, step_i, FlowStep(f"aba itens → lixeira ({item_id})"))
            step_i += 1
            ctx.step(flow, step_i, FlowStep("selecionar item e tocar lixeira"))
            step_i += 1
            # humano aperta "+" de 1 em 1 (com tremor): min(excess, 40) toques
            taps = min(excess, 40)
            for t in range(taps):
                ctx.step(flow, step_i, FlowStep(f"toque + ({t + 1}/{taps})",
                                                bias=(0.06, 0.22)))
                step_i += 1
            if excess > taps:
                ctx.step(flow, step_i, FlowStep("segmento longo de contagem",
                                                bias=(0.5, 1.2)))
                step_i += 1
            ctx.step(flow, step_i, FlowStep("confirmar YES", "DropItem",
                                            {"itemId": item_id, "count": excess},
                                            bias=(0.9, 2.1)))
            step_i += 1
            ctx.log("G3", f"descartou {excess}x {item_id} (teto {cap})")
            ctx.count("discards")
        ctx.step(flow, step_i, FlowStep("fechar mochila"))


def g4_evolve(ctx: BotContext) -> None:
    cfg = ctx.config["evolve"]
    flow = "evolução"
    with ctx.park():
        ctx.step(flow, 0, FlowStep("abrir menu pokébola", bias=(0.6, 1.1)))
        r = ctx.step(flow, 1, FlowStep("abrir treinadores", "GetInventory",
                                       {"section": "pokemon"}), quiet=False)
        if not r or r.get("State") == "shadow":
            ctx.log("G4", "evolução indisponível (extensão pendente) — sombra")
            ctx.step(flow, 2, FlowStep("fechar menu"))
            return
        mons = (r.get("data", {}) or {}).get("pokemon", [])
        cands = [m for m in mons
                 if m.get("ivPct", 0) >= cfg["min_iv"]
                 and m.get("candy", 0) >= m.get("candyToEvolve", 999)
                 and not m.get("favorite")]
        cands.sort(key=lambda m: -m.get("ivPct", 0))
        step_i = 2
        for m in cands[:cfg["max_per_session"]]:
            ctx.step(flow, step_i, FlowStep(f"filtrar/abrir {m.get('pokemonId')}"))
            step_i += 1
            ctx.step(flow, step_i, FlowStep("conferir doce e EVOLUIR", "EvolvePokemon",
                                            {"pokemonUid": m["uid"]},
                                            bias=(1.2, 2.4)))  # animação de evolução é longa
            step_i += 1
            ctx.step(flow, step_i, FlowStep("tela pós-evolução"))
            step_i += 1
            ctx.log("G4", f"evoluiu {m.get('pokemonId')} IV={m.get('ivPct', 0):.0f}%")
            ctx.count("evolves")
        best = [m for m in mons if m.get("ivPct", 0) >= cfg["favorite_iv"]]
        for m in best:
            if not m.get("favorite"):
                ctx.step(flow, step_i, FlowStep("favoritar guardião", "FavoritePokemon",
                                                {"pokemonUid": m["uid"], "favorite": True}))
                step_i += 1
                ctx.count("favorites")
        ctx.step(flow, step_i, FlowStep("fechar treinadores"))


def g5_idle(ctx: BotContext) -> None:
    micro_flows = {
        "camera": [FlowStep("arrastar câmera"), FlowStep("centralizar avatar")],
        "avatar": [FlowStep("abrir tela do avatar"), FlowStep("conferir equipamento"),
                   FlowStep("fechar")],
        "buddy":  [FlowStep("abrir buddy"), FlowStep("dar biscoito" if random.random() < 0.2
                                                     else "conferir distância"),
                   FlowStep("fechar")],
        "zoom":   [FlowStep("zoom out"), FlowStep("zoom in")],
        "menu":   [FlowStep("abrir pokébola"), FlowStep("olhar itens"),
                   FlowStep("fechar")],
    }
    name, steps = random.choice(list(micro_flows.items()))
    ctx.log("G5", f"ócio humano: {name}")
    ctx.steps(f"ocio-{name}", steps)
    ctx.count("idle")


@dataclass
class ActionGroup:
    name: str
    label: str
    fn: Callable[[BotContext], None]
    profile: TimingProfile
    cooldown_s: tuple[float, float]
    weight: float = 1.0


PROFILES = {
    "G1": TimingProfile("G1-caça", 237_000, 11_000, 0.42, 0.38, 0.14, 0.35,
                        0.22, (0.8, 2.6), 0.22),
    "G2": TimingProfile("G2-estoque", 173_000, 53_000, 0.65, 0.29, 0.06, 0.55,
                        0.12, (0.5, 1.7), 0.15),
    "G3": TimingProfile("G3-mochila", 311_000, 97_000, 0.83, 0.44, 0.03, 0.60,
                        0.31, (1.1, 3.4), 0.35),
    "G4": TimingProfile("G4-evolução", 197_000, 29_000, 1.05, 0.33, 0.02, 0.50,
                        0.27, (1.4, 4.2), 0.28),
    "G5": TimingProfile("G5-ócio", 421_000, 151_000, 0.55, 0.61, 0.09, 0.25,
                        0.41, (0.6, 5.1), 0.18),
}

GROUPS: list[ActionGroup] = [
    ActionGroup("G1", "caça/abordagem", g1_hunt, PROFILES["G1"], (35, 110), 3.0),
    ActionGroup("G2", "giro/estoque", g2_restock, PROFILES["G2"], (20, 75), 3.2),
    ActionGroup("G3", "mochila/descarte", g3_inventory, PROFILES["G3"], (600, 1500), 0.8),
    ActionGroup("G4", "evolução/guardiões", g4_evolve, PROFILES["G4"], (900, 2700), 0.5),
    ActionGroup("G5", "ócio humano", g5_idle, PROFILES["G5"], (45, 200), 2.2),
]

MARKOV = {
    None:  {"G1": 0.30, "G2": 0.30, "G5": 0.35, "G3": 0.03, "G4": 0.02},
    "G1":  {"G1": 0.42, "G2": 0.24, "G5": 0.22, "G3": 0.09, "G4": 0.03},
    "G2":  {"G1": 0.33, "G2": 0.30, "G5": 0.21, "G3": 0.13, "G4": 0.03},
    "G3":  {"G1": 0.24, "G2": 0.27, "G5": 0.36, "G3": 0.08, "G4": 0.05},
    "G4":  {"G1": 0.28, "G2": 0.28, "G5": 0.34, "G3": 0.08, "G4": 0.02},
    "G5":  {"G1": 0.34, "G2": 0.30, "G5": 0.24, "G3": 0.08, "G4": 0.04},
}


class Scheduler:
    def __init__(self, seed: int | None = None):
        self.seed = seed if seed is not None else secrets.randbits(64)
        self.rng = random.Random(self.seed)
        self.last: str | None = None
        self.cooldown_until: dict[str, float] = {g.name: 0.0 for g in GROUPS}

    def choose(self) -> ActionGroup:
        now = time.time()
        row = MARKOV[self.last]
        pool = [g for g in GROUPS if now >= self.cooldown_until[g.name]] or GROUPS[:1]
        weights = [row.get(g.name, 0.01) * g.weight for g in pool]
        pick = self.rng.choices(pool, weights=weights, k=1)[0]
        lo, hi = pick.cooldown_s
        self.cooldown_until[pick.name] = now + self.rng.uniform(lo, hi)
        self.last = pick.name
        return pick


def list_mesh() -> None:
    print("Malha de fingerprints (grupo → perfil):")
    for g in GROUPS:
        p = g.profile
        print(f"  {g.name} {g.label:18s} quantum={p.quantum_ns / 1000:.0f}µs "
              f"offset={p.offset_ns / 1000:.0f}µs lognormal(µ={p.mu}, σ={p.sigma}) "
              f"fadiga={p.drift_per_hour}/h hesita={p.hesitate_prob:.0%} "
              f"rajada={p.burst_prob:.0%} cooldown={g.cooldown_s}s")
    print("\nCada passo de fluxo deriva: rng = hash(sessão, grupo, fluxo, passo, seq)")
    print("→ delays nunca se repetem nem em loop infinito.")


def run(args: argparse.Namespace) -> None:
    if args.list_mesh:
        list_mesh()
        return
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    link = PogoLink()
    link.start_keepalive_monitor()
    caps = CapabilityRegistry(link)

    seed = secrets.randbits(64)
    ctx = BotContext(link, caps, config, solo=args.solo, seed=seed)
    ctx.tel.running = True
    ctx.tel.set_phase("starting")
    ctx.tel.write(force=True)

    print("[*] sondando plugin (keepalive ~3s)...")
    ctx.tel.set_phase("probing")
    ctx.tel.write(force=True)
    time.sleep(3.5)
    caps.probe()
    ctx.tel.caps_available = sorted(caps.available)
    ctx.tel.caps_shadow = sorted(caps.shadow)
    print(f"[+] disponíveis: {sorted(caps.available)}")
    print(f"[~] sombra (aguardando extensão nativa): {sorted(caps.shadow)}")
    if args.probe:
        ctx.tel.running = False
        ctx.tel.set_phase("stopped")
        ctx.tel.write(force=True)
        link.stop()
        return

    sched = Scheduler(seed)
    ctx.log("SYS", f"sessão iniciada seed={seed} modo={'solo' if args.solo else 'attached'}")
    # inventário inicial (IItemBag) para o painel já mostrar as contagens
    try:
        ctx.sample_inventory()
    except Exception:
        pass
    inv_next = time.time() + 60.0  # reamostra a cada ~60s (fora de encontros)
    try:
        while True:
            if not link.alive:
                ctx.tel.set_phase("waiting_game")
                ctx.tel.set_step("aguardando o jogo abrir/keepalive", None)
                ctx.tel.write(force=True)
                ctx.log("SYS", "keepalive ausente — jogo parado; dormindo 20s")
                time.sleep(20)
                continue
            g = sched.choose()
            ctx.group, ctx.profile = g.name, g.profile
            ctx.tel.set_group(g.name, g.label)
            ctx.tel.set_phase(GROUP_PHASE.get(g.name, "idle"))
            ctx.tel.write()
            try:
                g.fn(ctx)
            except Exception as e:
                ctx.tel.set_phase("error")
                ctx.log(g.name, f"erro contornado: {e}")
            # reamostra inventário fora do fluxo, em pausa humanizada
            if time.time() >= inv_next:
                try:
                    ctx.sample_inventory()
                except Exception:
                    pass
                inv_next = time.time() + random.uniform(45.0, 90.0)
            ctx.group, ctx.profile = "SYS", g.profile
            ctx.tel.set_group(None, None)
            ctx.tel.set_phase("contemplating")
            ctx.tel.set_step("pausa entre grupos (ritmo humano)", None)
            ctx.tel.write()
            ctx.seq += 1
            rng = random.Random(_seed_int(seed, "INTER", g.name, ctx.seq))
            ns = mesh_delay_ns(g.profile, rng, "entre-grupos", 0, ctx.seq,
                               (1.5, 4.5), time.time() - ctx.session_t0)
            ctx.log(g.name, f"ciclo completo; pausa {ns / NS:.3f}s")
            time.sleep(ns / NS)
    except KeyboardInterrupt:
        ctx.log("SYS", f"encerrado. stats={json.dumps(ctx.stats)}")
    except Exception as e:
        ctx.log("SYS", f"erro fatal contornado: {e}")
        ctx.tel.set_phase("error")
    finally:
        PAUSE_FILE.unlink(missing_ok=True)
        ctx.tel.running = False
        if ctx.tel.phase != "error":
            ctx.tel.set_phase("stopped")
        ctx.tel.write(force=True)
        link.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", action="store_true", help="cérebro comanda movimento")
    ap.add_argument("--probe", action="store_true", help="sondar ações ZMQ e sair")
    ap.add_argument("--list-mesh", action="store_true", help="imprimir malha e sair")
    run(ap.parse_args())
