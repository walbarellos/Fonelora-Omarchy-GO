package com.android.jmq.impl.gamebot;

import com.android.jmq.impl.RequestParser;

/**
 * Registra as ações de jogo no RequestParser (mesmo ponto de extensão que o
 * plugin usa para as 7 ações de localização).
 *
 * Chame GameBotActions.register(requestParser) em seguida das addExtraFunc
 * existentes no JMQServer.startJar, ou carregue via reflexão com o mesmo
 * DexClassLoader (padrão NianticLabs). Mantém a superfície do protocolo ZMQ:
 * cada ACTION vira uma chave aceita em {"Action":...}.
 *
 * Ações e seus ACTIONS (todos no envelope {"State":int,...}):
 *   GetNearby         lista spawns/pokéstops próximos (GetMapObjects)
 *   StartEncounter    inicia encontro (Encounter)
 *   ThrowBall         arremessa pokébola (CatchPokemon)
 *   FleeEncounter     foge do encontro (CatchPokemon.ShouldFlee)
 *   SpinFort          gira pokéstop (FortSearch)
 *   DropItem          descarta item (RecycleInventoryItem)
 *   EvolvePokemon     evolui pokémon (EvolvePokemon)
 *   FavoritePokemon   favorita/desfavorita (SetFavoritePokemon)
 *
 * Inventário não tem ação própria: é lido por CurrentInventory (novo), que
 * delega a IItemBag.GetItemCount na lib nativa.
 *   Status             probe de saúde/resolução (il2cpp bind, IRpcHandler)
 */
public final class GameBotActions {

    private GameBotActions() {}

    public static RequestParser register(RequestParser parser) {
        if (parser == null) return null;
        parser.addExtraFunc(GetNearbyRequest.ACTION,         GetNearbyRequest.class);
        parser.addExtraFunc(StartEncounterRequest.ACTION,    StartEncounterRequest.class);
        parser.addExtraFunc(ThrowBallRequest.ACTION,         ThrowBallRequest.class);
        parser.addExtraFunc(FleeEncounterRequest.ACTION,     FleeEncounterRequest.class);
        parser.addExtraFunc(SpinFortRequest.ACTION,          SpinFortRequest.class);
        parser.addExtraFunc(DropItemRequest.ACTION,          DropItemRequest.class);
        parser.addExtraFunc(EvolvePokemonRequest.ACTION,     EvolvePokemonRequest.class);
        parser.addExtraFunc(FavoritePokemonRequest.ACTION,   FavoritePokemonRequest.class);
        parser.addExtraFunc(CurrentInventoryRequest.ACTION,  CurrentInventoryRequest.class);
        parser.addExtraFunc(StatusRequest.ACTION,            StatusRequest.class);
        return parser;
    }
}
