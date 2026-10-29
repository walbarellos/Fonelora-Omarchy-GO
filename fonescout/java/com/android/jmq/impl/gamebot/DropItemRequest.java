package com.android.jmq.impl.gamebot;

import org.json.JSONObject;

/** Descarta item (RecycleInventoryItem/RecycleItemProto via SendRpc). */
public class DropItemRequest extends NativeGameRequest {
    public static final String ACTION = "DropItem";

    @Override protected String action() { return ACTION; }

    @Override
    protected String callNative(JSONObject p) {
        return GameBotNative.dropItem(p.optInt("item", 0), p.optInt("count", 1));
    }
}
