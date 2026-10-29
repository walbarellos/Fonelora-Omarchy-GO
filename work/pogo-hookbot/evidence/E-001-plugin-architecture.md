# E-001 — Arquitetura do plugin hook (assets/plugin.apk dentro de pokemon_custom.apk)

## Data
2026-10-28 | case pogo-hookbot | lead: apk-reverse

## Comando/Repro
```bash
unzip -o -j pokemon_custom.apk assets/plugin.apk -d /tmp/opencode/pogo-hookbot
unzip -l plugin.apk                       # estrutura
strings -n 3 plugin/classes.dex           # mineração de strings DEX
~/tools/jadx/bin/jadx -d plugin-jadx plugin.apk --no-res
cat plugin/configinfo_64.txt              # offsets il2cpp (extraído de pokemon_custom.apk assets)
```

## Achados
1. **Estrutura do plugin.apk**: classes.dex (8.8 MB, Kotlin), classes2.dex,
   `lib/arm64-v8a/libdobby.so` (hooking inline), `lib/arm64-v8a/libpluginmain.so`
   (5.9 MB, ponte JNI/hooks do jogo), `Snet.proto` (spoof de attestation),
   layouts de overlay (`float_iv_text.xml`).
2. **Servidor ZeroMQ**: `com.android.jmq.main.JMQServer`
   - REP `tcp://*:7878` (loop único recv→dispatch→send), protocolo JSON
     `{"Action": ..., "data": ...}` → `{"State": int, ...}`
   - PUB `tcp://*:7979` keepalive `{"Action":"KeepAlive"}` a cada 3 s
   - Registro de ações: `RequestConfig.sList` (estático: DeviceInfo, StateCheck)
     + `RequestParser.addExtraFunc` (runtime: SendPosition, CurrentPosition,
     IsLocationMock, StopMockLocation, Uninstall)
3. **Total de ações do plugin = 7, todas de localização/mock.** Nenhuma ação de
   jogo (giro/encontro/captura) existe hoje.
4. **Injeção de posição**: `LocationSaveRequest` → `LocationUtil.save()` +
   `getClassTest()` → reflection em
   `com.nianticlabs.nia.location.NianticLocationManager` (campo `myField`) →
   `notifyLocationUpdate(provider, Location, ServiceStatus)` para fused/gps/network,
   com Location spoofado (altitude/velocidade/acurácia/bearing fixos+rand,
   flag mock removida do Bundle).
5. **Hooks nativos** (`libpluginmain.so` + Dobby) aplicados por **offsets em
   libil2cpp.so** vindos de `configinfo_64.txt` (versão 0.433.1):
   - `addrExcellentOffset=0x128E6FC`, `addrDisplayExcellentOffset=0x129AB5C`
   - `addrIVOffset=0x1BE38CC` (base +0x54; atk/def/sta em +0x0/+0x4/+0x8)
   - `addrWildPokemonCPSetOffset=0x12A765C`, `...CPOnDestroy=0x12A77A8`
   - `addrLastPokeball{OffsetConstructor,Func}=0x1693CF0/0x1694078`
   - `addrUpdateFuncOffset=0xB7B964`, `addrVersionComparetoFuncOffset=0x522AFA0`
   - JNI exports: hookIVByAddress, hookPokemon/PokeStop/GymByAddress,
     hookExcellentByAddress, hookWildPokemonCP{Set,OnDestroy}ByAddress,
     callLastPokeballFunc, patchUpdateFunc, patchVersionComparetoFunc
6. **Neste build os hooks de leitura estão dormentes**: `InjectSoTool.hookNativeFunc`
   só instala patchVersionCompareto + PokeStop/Gym/Pokemon latlng, e o config
   desta versão NÃO traz os offsets addrPokeStop/Gym/PokemonLatLngOffset.
7. Loader do plugin está em `classes4.dex` do APK principal (chama
   `JMQServer.startJar()` e `InjectSoTool` via reflection/DexClassLoader).
8. Aparelho de teste: Infinix X6711, arm64-v8a, Android 14, **sem root**;
   `com.nianticlabs.pokemongo` instalado (build custom 0.433.1).

## Implicações (Finding → Path)
- Caminho de extensão escolhido: nova lib nativa própria (API il2cpp resolvida
  em runtime) + novas ações BaseRequest registradas via `addExtraFunc`, tudo
  dentro do processo já injetado — sem root, sem Frida, sem artefatos novos de
  detecção. Endereços/métodos a partir do dump Redux (metadata v39).
- O servidor telemetra ritmo: automação de UI não é necessária (chamadas diretas
  de métodos), mas o TEMPO de navegação de UI deve ser simulado → bot_brain.py.
