package com.android.jmq.impl.gamebot;

import org.json.JSONObject;

/** Inicia encontro com spawn (Encounter via SendRpc). */
public class StartEncounterRequest extends NativeGameRequest {
    public static final String ACTION = "StartEncounter";

    @Override protected String action() { return ACTION; }

    @Override
    protected String callNative(JSONObject p) {
        return GameBotNative.startEncounter(
                p.optLong("encounterId", 0),
                p.optString("spawnpointId", ""),
                p.optDouble("lat", 0), p.optDouble("lng", 0));
    }
}
