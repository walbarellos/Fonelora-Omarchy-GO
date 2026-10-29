package com.android.jmq.impl.gamebot;

import org.json.JSONObject;

/** Evolui pokémon (EvolvePokemon via SendRpc). */
public class EvolvePokemonRequest extends NativeGameRequest {
    public static final String ACTION = "EvolvePokemon";

    @Override protected String action() { return ACTION; }

    @Override
    protected String callNative(JSONObject p) {
        return GameBotNative.evolvePokemon(p.optLong("pokemonId", 0));
    }
}
