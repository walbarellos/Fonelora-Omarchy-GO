package com.android.jmq.impl.gamebot;

import org.json.JSONObject;

/**
 * Saúde + estado de resolução da lib nativa (il2cpp bind, IRpcHandler,
 * IItemBag). Não faz SendRpc — só relata se o hooking in-process está pronto.
 *
 * Útil como probe de handshake: força o load da libfonescout.so (via
 * GameBotNative.<clinit>) e devolve se il2cpp/rpchandler/itembag resolveram,
 * mesmo antes de qualquer ação de jogo real.
 *
 * Sem params.
 */
public class StatusRequest extends NativeGameRequest {
    public static final String ACTION = "Status";

    @Override protected String action() { return ACTION; }

    @Override
    protected String callNative(JSONObject p) {
        return GameBotNative.status();
    }
}
