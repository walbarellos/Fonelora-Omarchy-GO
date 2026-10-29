#!/usr/bin/env bash
# build.sh — monta o pokemon_custom.apk com as ações de jogo do bot (WI-007..009).
#
# Pipeline completo, reproduzível:
#   1. compila libfonescout.so (NDK, arm64)
#   2. compila as classes Java -> classes3.dex (javac + d8)
#   3. decompila o plugin.apk (apktool), injeta o registro GameBotActions no
#      JMQServer.startJar (smali) e reconstrói
#   4. injeta classes3.dex + libfonescout.so no plugin.apk
#   5. troca assets/plugin.apk dentro do pokemon_custom.apk
#   6. zipalign + assina com keystore própria (fonescout.keystore)
#
# Saída: build/pokemon_custom_fonescout.apk
#
# Requisitos (verificados abaixo): NDK, JDK, android.jar, d8, zipalign,
# apksigner, apktool, zip. O baksmali NAO e necessario: o dex novo vai como
# classes3.dex e o ART (Android 8+, alvo Android 14) carrega multidex nativo.
set -euo pipefail

# ---- config -----------------------------------------------------------------
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
NATIVE="$HERE/native"
JAVA_SRC="$HERE/java"
BUILD="$HERE/build"
OUT="$BUILD/out"

SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
NDK="${ANDROID_NDK_HOME:-$SDK/ndk/android-ndk-r27c}"
BT="$SDK/build-tools/34.0.0"
ANDROID_JAR="$SDK/platforms/android-34/android.jar"
APKTOOL_JAR="${APKTOOL_JAR:-/tmp/opencode/pogo-hookbot/apktool.jar}"
TARGET_APK="$REPO/pokemon_custom.apk"
KEYSTORE="$HERE/fonescout.keystore"
STOREPASS="fonescout"

# plugin decodificado (cache entre builds; apague para forçar decode limpo)
PLUGIN_DEC="$BUILD/plugin-decoded"

# ---- helpers ----------------------------------------------------------------
log() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "FALTA: $1"; exit 1; }; }
needf() { [ -f "$1" ] || { echo "FALTA arquivo: $1"; exit 1; }; }

log "0/6 verificando dependencias"
need javac; need java; need zip
needf "$ANDROID_JAR"; needf "$TARGET_APK"; needf "$APKTOOL_JAR"
needf "$BT/d8"; needf "$BT/zipalign"; needf "$BT/apksigner"
needf "$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android31-clang"

CLANG="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android31-clang"
rm -rf "$OUT"; mkdir -p "$OUT"

# ---- 1. lib nativa ----------------------------------------------------------
log "1/6 compilando libfonescout.so (arm64)"
( cd "$NATIVE" && "$CLANG" -shared -o "$OUT/libfonescout.so" fonescout.c \
    -I. -llog -ldl -O2 -fvisibility=hidden -Wall -Wextra )
needf "$OUT/libfonescout.so"

# ---- 2. classes Java -> dex -------------------------------------------------
log "2/6 compilando classes Java -> classes3.dex"
JAVASRC="$BUILD/src"
rm -rf "$JAVASRC" "$BUILD/classes"; mkdir -p "$JAVASRC" "$BUILD/classes"
# bases do plugin + stub de compilacao do RequestParser
mkdir -p "$JAVASRC/com/android/jmq/base" "$JAVASRC/com/android/jmq/impl"
cp /tmp/opencode/pogo-hookbot/plugin-jadx/sources/com/android/jmq/base/BaseRequest.java \
   /tmp/opencode/pogo-hookbot/plugin-jadx/sources/com/android/jmq/base/BaseResponse.java \
   "$JAVASRC/com/android/jmq/base/"
cp "$HERE/stub-src/com/android/jmq/impl/RequestParser.java" "$JAVASRC/com/android/jmq/impl/"
cp -r "$JAVA_SRC/com" "$JAVASRC/"
javac -source 8 -target 8 -nowarn -bootclasspath "$ANDROID_JAR" -cp "$ANDROID_JAR" \
      -d "$BUILD/classes" $(find "$JAVASRC" -name '*.java')
# remove o stub (o RequestParser real vive no dex do plugin) e as bases do
# plugin (BaseRequest/BaseResponse): ja estao no classes.dex original e
# duplicatas fariam o ART falhar com "Duplicate class".
rm -f "$BUILD/classes/com/android/jmq/impl/RequestParser.class"
rm -f "$BUILD/classes/com/android/jmq/base/BaseRequest.class" \
      "$BUILD/classes/com/android/jmq/base/BaseResponse.class"
"$BT/d8" --min-api 26 --output "$OUT" $(find "$BUILD/classes" -name '*.class')
needf "$OUT/classes.dex"

# ---- 3. plugin: decode + patch smali + build -------------------------------
log "3/6 decompilando plugin.apk (cache: $PLUGIN_DEC)"
PLUGIN_APK="$BUILD/plugin-orig.apk"
unzip -p "$TARGET_APK" assets/plugin.apk > "$PLUGIN_APK"
if [ ! -d "$PLUGIN_DEC" ]; then
    java -jar "$APKTOOL_JAR" d "$PLUGIN_APK" -o "$PLUGIN_DEC" -f
fi
needf "$PLUGIN_DEC/smali/com/android/jmq/main/JMQServer.smali"

# injeta o registro GameBotActions no startJar (idempotente)
JMQ="$PLUGIN_DEC/smali/com/android/jmq/main/JMQServer.smali"
if ! grep -q "GameBotActions" "$JMQ"; then
    log "3/6 injetando GameBotActions.register no JMQServer.startJar"
    python3 - "$JMQ" <<'PY'
import sys, re
p = sys.argv[1]
s = open(p).read()
# acha a ULTIMA addExtraFunc de startJar (a do "uninstall") e insere depois
m = None
for m in re.finditer(r'invoke-virtual \{v1, v2, p0\}, '
                     r'Lcom/android/jmq/impl/RequestParser;->addExtraFunc'
                     r'\(Ljava/lang/String;Ljava/lang/Class;\)'
                     r'Lcom/android/jmq/impl/RequestParser;', s):
    pass
if not m:
    sys.exit("ancora addExtraFunc nao encontrada")
inject = ('\n    invoke-static {v1}, Lcom/android/jmq/impl/gamebot/GameBotActions;'
          '->register(Lcom/android/jmq/impl/RequestParser;)'
          'Lcom/android/jmq/impl/RequestParser;\n\n'
          '    move-result-object v1\n')
s = s[:m.end()] + inject + s[m.end():]
open(p, "w").write(s)
print("injetado")
PY
else
    echo "registro ja presente"
fi

log "3/6 reconstruindo plugin.apk"
java -jar "$APKTOOL_JAR" b "$PLUGIN_DEC" -o "$BUILD/plugin-new.apk"

# ---- 4. injeta dex + lib no plugin -----------------------------------------
log "4/6 injetando classes3.dex + libfonescout.so no plugin.apk"
cp "$BUILD/plugin-new.apk" "$BUILD/plugin-final.apk"
# zip exige caminhos relativos corretos; monta estrutura temporaria
STAGE="$BUILD/stage"; rm -rf "$STAGE"; mkdir -p "$STAGE/lib/arm64-v8a"
cp "$OUT/classes.dex" "$STAGE/classes3.dex"
cp "$OUT/libfonescout.so" "$STAGE/lib/arm64-v8a/"
( cd "$STAGE" && zip -q "$BUILD/plugin-final.apk" classes3.dex lib/arm64-v8a/libfonescout.so )
unzip -l "$BUILD/plugin-final.apk" | grep -E "classes3.dex|fonescout" || { echo "injecao falhou"; exit 1; }

# ---- 5. troca assets/plugin.apk no APK principal ---------------------------
log "5/6 substituindo assets/plugin.apk no pokemon_custom.apk"
cp "$TARGET_APK" "$BUILD/pokemon_unsigned.apk"
# zip exige caminho relativo; monta estrutura assets/ e atualiza o entry
STAGE2="$BUILD/stage2"; rm -rf "$STAGE2"; mkdir -p "$STAGE2/assets"
cp "$BUILD/plugin-final.apk" "$STAGE2/assets/plugin.apk"
( cd "$STAGE2" && zip -q "$BUILD/pokemon_unsigned.apk" assets/plugin.apk )

# ---- 6. assina -------------------------------------------------------------
log "6/6 zipalign + assinatura"
if [ ! -f "$KEYSTORE" ]; then
    echo "criando keystore $KEYSTORE"
    keytool -genkeypair -v -keystore "$KEYSTORE" -alias fonescout \
            -keyalg RSA -keysize 2048 -validity 10000 \
            -storepass "$STOREPASS" -keypass "$STOREPASS" \
            -dname "CN=fonescout, OU=bot, O=fonescout, L=local, ST=local, C=BR" >/dev/null 2>&1
fi
"$BT/zipalign" -f -p 4 "$BUILD/pokemon_unsigned.apk" "$BUILD/pokemon_aligned.apk"
"$BT/apksigner" sign --ks "$KEYSTORE" --ks-pass "pass:$STOREPASS" \
    --key-pass "pass:$STOREPASS" --out "$OUT/pokemon_custom_fonescout.apk" \
    "$BUILD/pokemon_aligned.apk"

log "OK: $OUT/pokemon_custom_fonescout.apk"
echo
echo "Para instalar (a assinatura difere da debug original -> desinstale antes):"
echo "  adb uninstall com.nianticlabs.pokemongo   # o restorePlayData recupera o save"
echo "  adb install -r $OUT/pokemon_custom_fonescout.apk"
echo
echo "Validar o canal (WI-010): mande {\"Action\":\"Status\"} via pogolink e"
echo "confira State=200, il2cpp=1, rpchandler=1 no logcat (tag fonescout)."
