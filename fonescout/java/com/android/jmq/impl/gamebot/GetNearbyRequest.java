package com.android.jmq.impl.gamebot;

import org.json.JSONObject;

/** Lista spawns e pokéstops próximos (GetMapObjects via SendRpc). */
public class GetNearbyRequest extends NativeGameRequest {
    public static final String ACTION = "GetNearby";

    @Override protected String action() { return ACTION; }

    @Override
    protected String callNative(JSONObject p) {
        return GameBotNative.getNearby(
                p.optDouble("lat", 0), p.optDouble("lng", 0));
    }
}
