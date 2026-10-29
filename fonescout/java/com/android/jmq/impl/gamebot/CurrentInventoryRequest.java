package com.android.jmq.impl.gamebot;

import org.json.JSONObject;

/**
 * Lê contagem de um item do inventário cacheado (IItemBag.GetItemCount).
 *
 * Sem SendRpc: o inventário vive no estado do jogo, já sincronizado pelo
 * GetHoloholoInventory que o cliente faz sozinho. Lemos a mesma fonte que a
 * UI — mais barato e indistinguível de um jogador conferindo a bolsa.
 *
 * Params: {"item": <int enum Holoholo.Rpc.Item>}
 */
public class CurrentInventoryRequest extends NativeGameRequest {
    public static final String ACTION = "CurrentInventory";

    @Override protected String action() { return ACTION; }

    @Override
    protected String callNative(JSONObject p) {
        return GameBotNative.getItemCount(p.optInt("item", 0));
    }
}
