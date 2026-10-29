package com.android.jmq.impl.gamebot;

import org.json.JSONObject;

/** Gira pokéstop (FortSearch via SendRpc). */
public class SpinFortRequest extends NativeGameRequest {
    public static final String ACTION = "SpinFort";

    @Override protected String action() { return ACTION; }

    @Override
    protected String callNative(JSONObject p) {
        return GameBotNative.spinFort(
                p.optString("fortId", ""),
                p.optDouble("lat", 0), p.optDouble("lng", 0),
                p.optDouble("fortLat", 0), p.optDouble("fortLng", 0));
    }
}
