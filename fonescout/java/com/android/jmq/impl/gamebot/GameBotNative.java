package com.android.jmq.impl.gamebot;

import android.util.Log;

/**
 * Ponte JNI para a lib nativa libfonescout.so.
 *
 * A lib roda dentro do processo do jogo e despacha ações de jogo (encontro,
 * arremesso, giro de pokéstop, inventário, descarte, evolução, favoritar)
 * pelo mesmo canal RPC que o cliente legítimo usa (IRpcHandler.SendRpc).
 *
 * Todas as funções são static e devolvem o MESMO envelope JSON do plugin
 * ({"State":int,...}) para o bot_brain.py consumir sem mudança de protocolo.
 *
 * A lib é embutida no plugin.apk em lib/arm64-v8a/ e extraída pelo loader
 * para <cacheDir>/plugin/lib/arm64-v8a/. O DexClassLoader do plugin tem
 * librarySearchPath=null (não resolve nativeLibraryDir), então o load é feito
 * por System.load() com caminho ABSOLUTO apontando para o .so extraído.
 */
public final class GameBotNative {
    static {
        try {
            String path = nativeLibPath();
            if (path != null) {
                System.load(path);
                Log.i("GameBotNative", "loaded libfonescout.so from " + path);
            } else {
                Log.e("GameBotNative", "could not resolve libfonescout.so path");
            }
        } catch (UnsatisfiedLinkError e) {
            // lib ausente, ABI errada ou permissão; as chamadas responderão 503
            Log.e("GameBotNative", "load fonescout failed", e);
        }
    }

    /**
     * Monta o caminho absoluto do .so extraído pelo loader: o plugin.apk é
     * descompactado em <cacheDir>/plugin/, com as libs em lib/<ABI>/.
     * Obtém o Context via ActivityThread.currentApplication() (API ociosa,
     * sempre disponível depois do app iniciar — o load só ocorre na 1ª ação).
     */
    private static String nativeLibPath() {
        try {
            Class<?> at = Class.forName("android.app.ActivityThread");
            Object app = at.getMethod("currentApplication").invoke(null);
            if (!(app instanceof android.content.Context)) {
                return null;
            }
            String cache = ((android.content.Context) app).getCacheDir().getAbsolutePath();
            String abi = android.os.Build.SUPPORTED_ABIS[0]; // arm64-v8a
            return cache + "/plugin/lib/" + abi + "/libfonescout.so";
        } catch (Throwable t) {
            Log.e("GameBotNative", "nativeLibPath failed", t);
            return null;
        }
    }

    private GameBotNative() {}

    /** Saúde + estado de resolução (il2cpp bind / IRpcHandler). */
    public static native String status();

    /** Contagem de um item via IItemBag (inventário cacheado no jogo). */
    public static native String getItemCount(int item);

    // --- ações de jogo (WI-007/008) -------------------------------------
    // Cada uma devolve JSON com State=200 e os campos de resultado do OutProto.
    // Implementadas na lib; registradas no plugin via addExtraFunc (ver
    // GameBotActions).
    public static native String getNearby(double lat, double lng);
    public static native String startEncounter(long encounterId, String spawnpointId,
                                               double lat, double lng);
    public static native String throwBall(long encounterId, int pokeball,
                                          String spawnPointGuid,
                                          double reticleSize, double spinModifier,
                                          double hitPosition, boolean hitPokemon);
    public static native String fleeEncounter(long encounterId);
    public static native String spinFort(String fortId,
                                         double playerLat, double playerLng,
                                         double fortLat, double fortLng);
    public static native String dropItem(int item, int count);
    public static native String evolvePokemon(long pokemonId);
    public static native String favoritePokemon(long pokemonId, boolean favorite);
}
