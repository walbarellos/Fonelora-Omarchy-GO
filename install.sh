#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "=== Fonelora Omarchy GO - Instalador ==="

if [ ! -d "$DIR/.venv" ]; then
    echo "[*] Criando ambiente virtual Python..."
    python3 -m venv "$DIR/.venv"
fi

echo "[*] Instalando dependências (pyzmq)..."
"$DIR/.venv/bin/pip" install pyzmq

# Criar script wrapper em ~/.local/bin/fonelora
mkdir -p "$HOME/.local/bin"
cat << 'WRAPPER' > "$HOME/.local/bin/fonelora"
#!/usr/bin/env bash
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
FONELORA_DIR="$HOME/cracklab/fonelora-linux"

if [ -f "$FONELORA_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$FONELORA_DIR/.venv/bin/python3"
else
    PYTHON_BIN="python3"
fi

echo "Iniciando Fonelora Linux Daemon..."
nohup "$PYTHON_BIN" "$FONELORA_DIR/server.py" > /tmp/fonelora.log 2>&1 &
PID=$!
sleep 1
if xdg-open http://127.0.0.1:18438 2>/dev/null; then
    echo "Painel Web aberto em http://127.0.0.1:18438 (PID: $PID)"
fi
WRAPPER

chmod +x "$HOME/.local/bin/fonelora"

# Criar entrada desktop
mkdir -p "$HOME/.local/share/applications"
cat << DESKTOP > "$HOME/.local/share/applications/fonelora.desktop"
[Desktop Entry]
Name=Fonelora Linux
Comment=GPS Location Changer para Linux / Omarchy
Exec=$HOME/.local/bin/fonelora
Icon=applications-games
Terminal=false
Type=Application
Categories=Utility;Game;
DESKTOP

echo "[✓] Instalação concluída!"
echo "Você pode iniciar digitando 'fonelora' no terminal ou buscando no menu do Hyprland/Omarchy."
