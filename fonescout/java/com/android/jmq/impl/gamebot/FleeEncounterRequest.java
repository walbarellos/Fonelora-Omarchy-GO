package com.android.jmq.impl.gamebot;

import org.json.JSONObject;

/** Foge do encontro (CatchPokemon com ShouldFlee, via SendRpc). */
public class FleeEncounterRequest extends NativeGameRequest {
    public static final String ACTION = "FleeEncounter";

    @Override protected String action() { return ACTION; }

    @Override
    protected String callNative(JSONObject p) {
        return GameBotNative.fleeEncounter(p.optLong("encounterId", 0));
    }
}
