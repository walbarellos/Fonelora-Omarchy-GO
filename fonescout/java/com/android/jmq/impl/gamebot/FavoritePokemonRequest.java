package com.android.jmq.impl.gamebot;

import org.json.JSONObject;

/** Favorita/desfavorita pokémon (SetFavoritePokemon via SendRpc). */
public class FavoritePokemonRequest extends NativeGameRequest {
    public static final String ACTION = "FavoritePokemon";

    @Override protected String action() { return ACTION; }

    @Override
    protected String callNative(JSONObject p) {
        return GameBotNative.favoritePokemon(
                p.optLong("pokemonId", 0), p.optBoolean("favorite", true));
    }
}
