package com.android.jmq.impl.gamebot;

import org.json.JSONObject;

/** Arremessa pokébola (CatchPokemon via SendRpc). */
public class ThrowBallRequest extends NativeGameRequest {
    public static final String ACTION = "ThrowBall";

    @Override protected String action() { return ACTION; }

    @Override
    protected String callNative(JSONObject p) {
        return GameBotNative.throwBall(
                p.optLong("encounterId", 0),
                p.optInt("pokeball", 1),
                p.optString("spawnPointGuid", ""),
                p.optDouble("reticleSize", 0.5),
                p.optDouble("spinModifier", 0),
                p.optDouble("hitPosition", 0.5),
                p.optBoolean("hitPokemon", true));
    }
}
