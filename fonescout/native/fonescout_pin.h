/*
 * fonescout_pin.h — endereços fixados para a versão pinada 0.433.1.
 *
 * Gerado do dump Redux (E-003). Cada campo e um RVA (offset relativo ao base
 * do libil2cpp.so) ou um MethodInfo* global. SO vale para 0.433.1: atualizar
 * o jogo exige regerar isto do novo dump (WI-005 e repetivel).
 *
 * A maioria das resolucoes em fonescout.c e feita por NOME (il2cpp API), nao
 * por endereco — isso e de proposito: nomes de classe/metodo sao estaveis e
 * o codigo fica legivel. So fixamos endereco onde a API por nome nao chega,
 * nomeadamente os MethodInfo* de metodos GENERICOS (SendRpc<In,Out>), cuja
 * instancia inflada nao e alcancavel por class_get_method_from_name.
 *
 * Pendente (WI-010): preencher generic_send com o MethodInfo* exato de cada
 * par (InProto,OutProto) apos validacao em dispositivo. Os candidatos do
 * dump (ver E-003 F-010) estao em comments abaixo.
 */
#ifndef FONESCOUT_PIN_H
#define FONESCOUT_PIN_H

/* RVA de RpcHandlerExt.Send<,> instancia compartilhada (ver E-003 F-010):
 *   0x05F71990  RpcHandlerExt_Send_1(IRpcHandler*, Method__Enum, Object*, MethodInfo*)
 * Nao usado diretamente (chamamos via MethodInfo*), mantido como referencia
 * para depuracao em caso de o metodo nao-genereo ser necessario. */
#define RVA_RPCHANDLEREXT_SEND_SHARED  0x05F71990

/*
 * Metodos genericos de RpcHandler — candidatos a MethodInfo* por par de proto.
 * Cada DO_APP_FUNC_METHODINFO abaixo e um MethodInfo* global no dump. O mapeamento
 * exato par->indice e determinado em WI-010 (inspecao em dispositivo), pois o
 * dump nao rotula os argumentos genericos de cada instancia.
 *
 *   0x0EC10DE8  IRpcHandler_SendRpc_1__MethodInfo
 *   0x0EC10DF0  IRpcHandler_SendRpc_2__MethodInfo
 *   0x0EC10DF8  IRpcHandler_SendRpc_3__MethodInfo
 *   0x0EC10E00  IRpcHandler_SendRpc_4__MethodInfo
 *   0x0EC10E08  IRpcHandler_SendRpc_5__MethodInfo
 *   0x0EC10E10  IRpcHandler_SendRpc_6__MethodInfo
 *   0x0EC23A58  RpcHandlerExt_Send_5__MethodInfo
 *   0x0EC23A60  RpcHandlerExt_Send_6__MethodInfo
 *   ... (5..10)
 */

/* Tabela preenchida em WI-010. Por enquanto vazia: acao de exemplo que usa
 * SendRpc retorna "no-plan" ate a pinagem ser calibrada. */
typedef struct {
    int        methodId;      /* Holoholo.Rpc.Method enum */
    const char* inProtoNs;    /* namespace do proto de entrada */
    const char* inProtoName;
    unsigned long rvaGenericSend; /* RVA do MethodInfo* da instancia generica */
} FonescoutRpcPin;

static const FonescoutRpcPin kRpcPins[] = {
    /* { 102, "Holoholo.Rpc", "EncounterProto",       0x0EC10DE8 }, // Encounter   */
    /* { 103, "Holoholo.Rpc", "CatchPokemonProto",    0x0EC10DF0 }, // CatchPokemon */
    /* { 101, "Holoholo.Rpc", "FortSearchProto",      0x0EC10DF8 }, // FortSearch   */
    /* { 106, "Holoholo.Rpc", "GetMapObjectsProto",   0x0EC10E00 }, // GetMapObjects*/
    /* { 137, "Holoholo.Rpc", "RecycleItemProto",     0x0EC10E08 }, // DropItem     */
    /* { 125, "Holoholo.Rpc", "EvolvePokemonProto",   0x0EC10E10 }, // Evolve       */
    /* { 148, "Holoholo.Rpc", "SetFavoritePokemonProto", ...      }, // Favorite     */
    { 0, NULL, NULL, 0 } /* terminador */
};

#endif /* FONESCOUT_PIN_H */
