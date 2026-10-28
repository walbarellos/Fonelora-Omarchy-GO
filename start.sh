#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$DIR/.venv/bin/python3" ]; then
    PY="$DIR/.venv/bin/python3"
else
    PY="python3"
fi

echo "[*] Iniciando Fonelora Server em http://127.0.0.1:18438..."
"$PY" "$DIR/server.py"
