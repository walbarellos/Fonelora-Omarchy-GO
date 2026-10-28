# Fonelora-Omarchy-GO 🎮🗺️

Versão nativa para Linux (Arch / Omarchy / Hyprland) do **Fonelora Location Changer**, com suporte completo a simulação de GPS Android via ADB (USB ou Wi-Fi) e **bypass do Erro 12 da Niantic** para o Pokémon GO sem necessidade de root.

---

## 🌟 Recursos

- **Bypass do Erro 12 no Pokémon GO:** Comunicação direta com o motor interno do jogo via protocolo ZeroMQ na porta `7878` (injeção direta em `NianticLocationManager`), eliminando flags de mock do sistema operacional.
- **Painel Web Completo:** Interface moderna em Leaflet com mapa em tempo real (`http://127.0.0.1:18438`).
- **Controle por Joystick Virtual e Teclado:** Controle de movimento em 360° com teclas **W, A, S, D**.
- **Velocidades Configuráveis:** Caminhada (1.0 m/s ou ~3.6 km/h) para segurança total contra detecção e ban.
- **Rotas Multi-pontos e Importação de GPX:** Planeje trajetos e simule caminhadas automáticas.
- **Calculadora de Cooldown:** Tempo de espera embutido para evitar soft-bans por pulos de coordenadas.

---

## 📁 Estrutura do Projeto

- `server.py`: Servidor HTTP e backend em Python que gerencia as conexões ADB, Socket TCP (38438) e ZeroMQ (7878).
- `index.html`: Interface visual interativa com mapa Leaflet, Joystick, Teleporte e Rotas.
- `install.sh`: Script de instalação automática de dependências e atalhos no sistema.
- `start.sh`: Script rápido para iniciar o servidor Fonelora.
- `pokemon_custom.apk`: APK modificado do Pokémon GO fornecido pelo Fonelora (versão 0.433.1.0 com plugin hook).
- `gpslocate.apk`: Assistente oficial Fonelora para outros aplicativos gerais do Android (Google Maps, apps de entrega, etc).

---

## 🚀 Instalação Rápida

1. Clone o repositório ou navegue até a pasta:
   ```bash
   git clone git@github.com:walbarellos/Fonelora-Omarchy-GO.git
   cd Fonelora-Omarchy-GO
   ```

2. Execute o instalador:
   ```bash
   ./install.sh
   ```

---

## 🎮 Como Usar com o Pokémon GO (Anti-Erro 12)

### 1. Preparar o Celular (Apenas na 1ª vez)
1. Instale o APK modificado do jogo contido nesta pasta:
   ```bash
   adb install -r pokemon_custom.apk
   ```
2. No celular, vá em **Configurações > Aplicativos > Pokémon GO > Permissões**:
   - Conceda **Localização** (Permitir o tempo todo / Localização precisa).
   - Conceda **Acesso a todos os arquivos** (`MANAGE_EXTERNAL_STORAGE`).
3. Nas **Opções do Desenvolvedor** do celular:
   - Em **"Selecionar app de local fictício" (Mock location)**, certifique-se de deixar como **"Nenhum"** (o APK do Fonelora injeta a localização internamente via memória, não use o app de mock externo no Pokémon GO).

### 2. Iniciar o Fonelora no Linux
Você pode simplesmente digitar no seu terminal ou buscar no Hyprland:
```bash
fonelora
```
Ou rodar manualmente:
```bash
./start.sh
```
O painel abrirá automaticamente em `http://127.0.0.1:18438`.

### 3. Jogar!
- Abra o Pokémon GO no celular.
- No painel web do PC, use o **Joystick (WASD)** ou clique no mapa para andar na velocidade de caminhada (~1 m/s ou ~3.6 km/h).
- O backend enviará os sinais em tempo real via ZeroMQ direto para o hook do jogo.

---

## 🛠️ Tecnologias
- **Python 3** + **PyZMQ**
- **Android Debug Bridge (ADB)**
- **Leaflet.js** + **OpenStreetMap**
