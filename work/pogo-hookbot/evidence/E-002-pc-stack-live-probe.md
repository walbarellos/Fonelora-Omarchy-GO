# E-002 — Stack PC validada ao vivo (pogolink + bot_brain + walk_loop)

## Data
2026-10-28 | case pogo-hookbot

## Comando/Repro
```bash
cd fonelora-linux
.venv/bin/python3 bot_brain.py --list-mesh
.venv/bin/python3 bot_brain.py --probe      # celular conectado via adb TLS
```

## Resultado (probe real, dispositivo Infinix X6711)
- keepalive recebido (plugin ativo no jogo)
- disponíveis: `CurrentPosition`, `SendPosition` (State=200)
- sombra (State=400 → plugin não conhece): DropItem, EvolvePokemon,
  FavoritePokemon, FleeEncounter, GetEncounterState, GetInventory, GetNearby,
  GetPlayerStats, OpenFort, SpinFort, StartEncounter, ThrowBall (12 ações)

## Artefatos novos no repositório
- `pogolink.py` — cliente ZMQ REQ robusto (auto-recriação de socket em timeout,
  re-forward adb, monitor de keepalive 7979).
- `bot_brain.py` v2 — malha 4D de fingerprints (grupo, fluxo, passo, sequência),
  perfis distintos por grupo (quantum 173–421 µs, lognormal, fadiga, hesitações,
  rajadas), scheduler Markoviano com cooldowns, modo sombra por ação,
  pausa do walk_loop via arquivo `.bot_pause`.
- `bot_config.json` — política de descarte (teto por item; itens ausentes nunca
  são tocados), política de caça (CP/IV), evolução (IV mínimo/favoritar).
- `walk_loop.py` — patch: `maybe_pause()` segura posição com jitter humano
  enquanto `.bot_pause` existir.

## Nota de segurança
Sonda NUNCA envia `StopMockLocation` (desligaria o mock de localização).
