/*
 * fonescout.c — lib nativa JNI (arm64) que aciona ações de jogo via API il2cpp
 * em runtime, dentro do processo do Pokémon GO 0.433.1 (sem root).
 *
 * Papel no sistema:
 *   PC (pogolink) --ZMQ:7878--> plugin Java (JMQServer) --JNI--> ESTA LIB
 *        --il2cpp--> IRpcHandler.SendRpc(method, proto) --> servidor Niantic
 *
 * A lib NÃO faz hook nem patch. Ela constrói os mesmos protos que o cliente
 * legítimo construiria e os despacha pelo mesmo gargalo (IRpcHandler.SendRpc).
 * Isso é intencional: o trafego gerado é indistinguível do de um jogador real;
 * só o *quando* (timing) é orquestrado pelo bot_brain fora.
 *
 * Arquitetura de resolução (por que não precisa do dump em tempo de build):
 *   - símbolos il2cpp -> dlsym na libil2cpp.so já carregada pelo Unity
 *   - classes/metodos -> il2cpp_class_from_name + get_method_from_name
 *   - instancias de servico -> Zenject ProjectContext.Instance.Container.Resolve(Type)
 * Endereços/offsets que variam por versao (RVAs de MethodInfo generico) sao
 * fixados em fonescout_pin.h, gerado do dump para a versao 0.433.1.
 */
#include <jni.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <dlfcn.h>
#include <pthread.h>
#include <android/log.h>
#include <unistd.h>
#include <setjmp.h>
#include <signal.h>

#include "il2cpp_api.h"
#include "fonescout_pin.h"

#define TAG "fonescout"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

/* Timeout do await_promise: margem folgada p/ RTT de rede + fila do jogo.
 * O timing humanizado (quando disparar) e do bot_brain; aqui so limitamos
 * quanto esperamos a resposta. */
#define RPC_TIMEOUT_MS 8000

static Il2CppApi g_api;
static bool      g_ready = false;

/* ================================================================== */
/* bind da API il2cpp                                                   */
/* ================================================================== */
#define BIND(field, name)                                          \
    do {                                                           \
        g_api.field = (void*)dlsym(handle, name);                  \
        if (!g_api.field) { LOGE("dlsym miss: %s", name); miss++; } \
    } while (0)

int fonescout_il2cpp_bind(Il2CppApi* api, void* handle) {
    int miss = 0;
    BIND(domain_get,                "il2cpp_domain_get");
    BIND(domain_get_assemblies,     "il2cpp_domain_get_assemblies");
    BIND(assembly_get_image,        "il2cpp_assembly_get_image");
    BIND(class_from_name,           "il2cpp_class_from_name");
    BIND(class_get_method_from_name,"il2cpp_class_get_method_from_name");
    BIND(class_get_field_from_name, "il2cpp_class_get_field_from_name");
    BIND(field_get_offset,          "il2cpp_field_get_offset");
    BIND(field_get_value,           "il2cpp_field_get_value");
    BIND(field_set_value,           "il2cpp_field_set_value");
    BIND(field_get_value_object,    "il2cpp_field_get_value_object");
    BIND(object_new,                "il2cpp_object_new");
    BIND(runtime_invoke,            "il2cpp_runtime_invoke");
    BIND(string_new,                "il2cpp_string_new");
    BIND(string_length,             "il2cpp_string_length");
    BIND(string_chars,              "il2cpp_string_chars");
    BIND(class_get_type,            "il2cpp_class_get_type");
    BIND(type_get_object,           "il2cpp_type_get_object");
    BIND(class_get_name,            "il2cpp_class_get_name");
    BIND(class_get_namespace,       "il2cpp_class_get_namespace");
    BIND(class_get_methods,         "il2cpp_class_get_methods");
    if (api) *api = g_api;
    return miss; /* 0 = todos resolvidos */
}

bool fonescout_il2cpp_ready(void) { return g_ready; }
Il2CppApi* fonescout_il2cpp(void) { return &g_api; }

/* ================================================================== */
/* helpers de resolução                                                 */
/* ================================================================== */

/* Acha a imagem (assembly) do jogo que contem `ns`.`cls`. */
static const Il2CppImage* find_image(const char* ns, const char* cls) {
    size_t n = 0;
    const Il2CppAssembly** asms = g_api.domain_get_assemblies(g_api.domain_get(), &n);
    for (size_t i = 0; i < n; i++) {
        const Il2CppImage* img = g_api.assembly_get_image(asms[i]);
        if (!img) continue;
        if (g_api.class_from_name(img, ns, cls)) return img;
    }
    return NULL;
}

/* Resolve classe por (namespace, nome) em qualquer assembly. */
static Il2CppClass* find_class(const char* ns, const char* cls) {
    const Il2CppImage* img = find_image(ns, cls);
    return img ? g_api.class_from_name(img, ns, cls) : NULL;
}

/* Resolve um metodo nao-generico por nome+argc. NULL se nao achar. */
static const MethodInfo* find_method(Il2CppClass* k, const char* name, int argc) {
    return k ? g_api.class_get_method_from_name(k, name, argc) : NULL;
}

/* Le campo int64/bool de um objeto. */
static int64_t  get_obj_i64   (Il2CppObject* o, const FieldInfo* f) { int64_t v=0;  if(o&&f) g_api.field_get_value(o,f,&v); return v; }
static int32_t  get_obj_i32   (Il2CppObject* o, const FieldInfo* f) { int32_t v=0;  if(o&&f) g_api.field_get_value(o,f,&v); return v; }
static bool     get_obj_bool  (Il2CppObject* o, const FieldInfo* f) { uint8_t v=0;  if(o&&f) g_api.field_get_value(o,f,&v); return v!=0; }

static const FieldInfo* fld(Il2CppClass* k, const char* name) {
    return k ? g_api.class_get_field_from_name(k, name) : NULL;
}

/* ================================================================== */
/* resolução do canal RPC + inventário diretamente via Unity Engine    */
/* ================================================================== */

static Il2CppObject* resolve_rpc_handler_direct(void) {
    Il2CppClass* objCls = find_class("UnityEngine", "Object");
    if (!objCls) { 
        LOGE("UnityEngine.Object not found"); 
        return NULL; 
    }

    const MethodInfo* findMethod = find_method(objCls, "FindFirstObjectByType", 1);
    if (!findMethod) findMethod = find_method(objCls, "FindObjectOfType", 1);
    if (!findMethod) { 
        LOGE("FindObjectOfType / FindFirstObjectByType not found"); 
        return NULL; 
    }

    Il2CppClass* rpcCls = find_class("Niantic.Holoholo.Rpc", "RpcHandler");
    if (!rpcCls) { 
        LOGE("RpcHandler class not found"); 
        return NULL; 
    }

    const Il2CppType* t = g_api.class_get_type(rpcCls);
    Il2CppObject* typeObj = g_api.type_get_object(t);
    if (!typeObj) { 
        LOGE("typeObj for RpcHandler is null"); 
        return NULL; 
    }

    void* args[1] = { typeObj };
    Il2CppException* exc = NULL;
    Il2CppObject* handler = g_api.runtime_invoke(findMethod, NULL, args, &exc);
    if (exc || !handler) { 
        LOGE("FindFirstObjectByType(RpcHandler) returned null"); 
        return NULL; 
    }

    LOGI(">>> RpcHandler resolvido diretamente via Unity: %p <<<", (void*)handler);
    return handler;
}

static Il2CppObject* g_rpcHandler = NULL;
static Il2CppObject* g_itemBag    = NULL;

static bool resolve_rpc_handler(void) {
    g_rpcHandler = resolve_rpc_handler_direct();
    if (!g_rpcHandler) return false;
    LOGI("IRpcHandler resolved: %p", (void*)g_rpcHandler);
    return true;
}

static void resolve_item_bag(void) {
    /* ItemBag será resolvido a partir do container ou via inventário nativo */
}

/* ================================================================== */
/* construção de proto de entrada                                       */
/* ================================================================== */
/*
 * Constroi um proto il2cpp e preenche campos por nome. Campos ausentes ficam
 * default (0/null), igual a um proto recem-criado no cliente legitimo.
 * `fields` e uma tabela terminada por nome==NULL.
 */
typedef struct { const char* name; int kind; double num; const char* str; } ProtoField;
enum { F_I64 = 1, F_DBL = 2, F_BOOL = 3, F_STR = 4, F_INT = 5 };
#define TERMINATOR { NULL, 0, 0, NULL }

static Il2CppObject* build_proto(Il2CppClass* k, const ProtoField* fields) {
    if (!k) return NULL;
    Il2CppObject* obj = g_api.object_new(k);
    if (!obj) return NULL;
    for (const ProtoField* f = fields; f && f->name; f++) {
        const FieldInfo* fi = fld(k, f->name);
        if (!fi) { LOGI("field miss: %s", f->name); continue; }
        switch (f->kind) {
            case F_INT:  { int32_t v = (int32_t)f->num;  g_api.field_set_value(obj, fi, &v); break; }
            case F_I64:  { int64_t v = (int64_t)f->num;  g_api.field_set_value(obj, fi, &v); break; }
            case F_DBL:  { double  v = f->num;           g_api.field_set_value(obj, fi, &v); break; }
            case F_BOOL: { uint8_t v = f->num ? 1 : 0;   g_api.field_set_value(obj, fi, &v); break; }
            case F_STR:  { Il2CppString* s = g_api.string_new(f->str ? f->str : "");
                           g_api.field_set_value(obj, fi, s); break; }
        }
    }
    return obj;
}

/* ================================================================== */
/* despacho SendRpc (generico, compartilhado) + leitura de resposta     */
/* ================================================================== */
/*
 * RpcHandlerExt.Send<InProto,OutProto>(this IRpcHandler, Method, InProto)
 *   -> um unico blob nativo compartilhado (ver E-003 F-010).
 * O MethodInfo* com o contexto generico real e fixado por par (In,Out) em
 * fonescout_pin.h (kRpcPins), gerado do dump desta versao. Sem ele,
 * runtime_invoke nao saberia o tipo do retorno (System.Object partilhado).
 */
static const MethodInfo* resolve_send_mi(unsigned long rvaGenericSend) {
    /* O MethodInfo* e um global de dados no libil2cpp.so. Precisamos do base
       do modulo + RVA. dladdr no proprio simbolo qualquer nos da o base. */
    if (!rvaGenericSend) return NULL;
    Dl_info info;
    void* anySym = (void*)(uintptr_t)g_api.domain_get; /* simbolo ja no modulo */
    if (dladdr(anySym, &info) && info.dli_fbase) {
        return (const MethodInfo*)((uintptr_t)info.dli_fbase + rvaGenericSend);
    }
    return NULL;
}

/* Poll do IRpcPromise ate Promise.completedValue estar preenchido (F-010). */
static Il2CppObject* await_promise(Il2CppObject* promise, int timeout_ms) {
    if (!promise) return NULL;
    Il2CppClass* k = find_class("Niantic.Promises", "Promise`1");
    if (!k) { LOGE("Promise`1 not found"); return NULL; }
    const FieldInfo* fComplete = fld(k, "completeCalled");
    const FieldInfo* fValue    = fld(k, "completedValue");
    if (!fComplete || !fValue) { LOGE("Promise fields not found"); return NULL; }
    int waited = 0;
    while (waited <= timeout_ms) {
        if (get_obj_bool(promise, fComplete))
            return g_api.field_get_value_object(fValue, promise);
        usleep(50 * 1000); /* 50ms; o timing humanizado e do bot_brain */
        waited += 50;
    }
    LOGI("await_promise timeout %d ms", timeout_ms);
    return NULL;
}

/*
 * Ação RPC completa: constroi proto de entrada (tabela `inFields`), despacha
 * pelo pin correspondente a `methodId`, espera a resposta e devolve o OutProto
 * (ou NULL). O caller entao extrai os campos de resultado e monta o JSON.
 */
static Il2CppObject* rpc_call(int methodId, const char* inNs, const char* inName,
                              const ProtoField* inFields) {
    if (!g_ready || !g_rpcHandler)
        return NULL;
    /* acha o pin desta ação */
    const FonescoutRpcPin* pin = NULL;
    for (const FonescoutRpcPin* p = kRpcPins; p && p->inProtoName; p++)
        if (p->methodId == methodId) { pin = p; break; }
    if (!pin) { LOGI("no pin for method %d (WI-010 pendente)", methodId); return NULL; }

    Il2CppClass* inK = find_class(inNs, inName);
    if (!inK) { LOGE("proto %s.%s not found", inNs, inName); return NULL; }
    Il2CppObject* inProto = build_proto(inK, inFields);
    if (!inProto) return NULL;

    const MethodInfo* mi = resolve_send_mi(pin->rvaGenericSend);
    if (!mi) { LOGE("generic Send MethodInfo null for %d", methodId); return NULL; }

    void* args[2] = { (void*)(intptr_t)methodId, inProto };
    Il2CppException* exc = NULL;
    Il2CppObject* promise = g_api.runtime_invoke(mi, g_rpcHandler, args, &exc);
    if (exc || !promise) { LOGE("SendRpc(%d) invoke failed", methodId); return NULL; }

    return await_promise(promise, RPC_TIMEOUT_MS);
}

/* ================================================================== */
/* helpers de resposta -> JSON                                          */
/* ================================================================== */
/* enum Holoholo.Rpc.Method (E-003 F-007) */
enum {
    M_GET_PLAYER = 2, M_GET_HOLOHOLO_INVENTORY = 4,
    M_FORT_SEARCH = 101, M_ENCOUNTER = 102, M_CATCH_POKEMON = 103,
    M_GET_MAP_OBJECTS = 106, M_RELEASE = 112,
    M_EVOLVE = 125, M_RECYCLE_ITEM = 137, M_SET_FAVORITE = 148
};

/* ================================================================== */
/* ações exportadas via JNI                                             */
/* ================================================================== */
/*
 * Espelha o protocolo ZMQ do plugin. Cada função devolve um JSON curto no
 * mesmo formato BaseResponse ({"State":200,...}) para o bot_brain consumir
 * sem mudanca.
 */

/* Saude + estado de resolucao (usado no WI-010 para validar o bind). */
JNIEXPORT jstring JNICALL
Java_com_android_jmq_impl_gamebot_GameBotNative_status(JNIEnv* env, jclass cls) {
    (void)cls;
    char buf[160];
    snprintf(buf, sizeof buf,
             "{\"State\":%d,\"il2cpp\":%d,\"rpchandler\":%d,\"itembag\":%d}",
             g_ready ? 200 : 503, g_ready ? 1 : 0,
             g_rpcHandler ? 1 : 0, g_itemBag ? 1 : 0);
    return (*env)->NewStringUTF(env, buf);
}

/* CurrentInventory — IItemBag.GetItemCount(Item), nao-genereo.
 * Le o inventario ja cacheado no jogo (mesmo fonte que a UI) — nao precisa
 * decodificar o proto de inventario (ver E-003 F-009). */
JNIEXPORT jstring JNICALL
Java_com_android_jmq_impl_gamebot_GameBotNative_getItemCount(JNIEnv* env, jclass cls, jint item) {
    (void)cls;
    char buf[128];
    if (!g_ready || !g_itemBag)
        return (*env)->NewStringUTF(env, "{\"State\":503,\"Msg\":\"not-ready\"}");
    Il2CppClass* bagCls = find_class("Niantic.Holoholo", "IItemBag");
    const MethodInfo* m = find_method(bagCls, "GetItemCount", 1);
    if (!m)
        return (*env)->NewStringUTF(env, "{\"State\":500,\"Msg\":\"no-GetItemCount\"}");
    int32_t itemVal = item;
    void* args[1] = { &itemVal };
    Il2CppException* exc = NULL;
    Il2CppObject* r = g_api.runtime_invoke(m, g_itemBag, args, &exc);
    if (exc || !r)
        return (*env)->NewStringUTF(env, "{\"State\":502,\"Msg\":\"invoke-failed\"}");
    /* retorna int32 embutido no boxed (header Il2CppObject + payload) */
    int32_t count = 0;
    memcpy(&count, (char*)r + 0x10, sizeof count);
    snprintf(buf, sizeof buf, "{\"State\":200,\"item\":%d,\"count\":%d}", item, count);
    return (*env)->NewStringUTF(env, buf);
}

/* --- ações SendRpc ------------------------------------------------- */

/* GetNearby (GetMapObjects 106). Devolve o numero de spawns+fortes na area
 * (parse completo do ClientMapCellProto e feito no bot_brain quando
 * precisar; aqui confirmamos que o RPC respondeu). */
JNIEXPORT jstring JNICALL
Java_com_android_jmq_impl_gamebot_GameBotNative_getNearby(JNIEnv* env, jclass cls,
                                                           jdouble lat, jdouble lng) {
    (void)cls;
    char buf[200];
    ProtoField in[] = {
        { "PlayerLat", F_DBL, lat, NULL },
        { "PlayerLng", F_DBL, lng, NULL },
        TERMINATOR
    };
    Il2CppObject* out = rpc_call(M_GET_MAP_OBJECTS, "Holoholo.Rpc", "GetMapObjectsProto", in);
    if (!out)
        return (*env)->NewStringUTF(env, "{\"State\":503,\"Msg\":\"rpc-no-pin-or-timeout\"}");
    /* GetMapObjectsOutProto.MapCell e repeated; devolvemos Status como probe. */
    Il2CppClass* outK = find_class("Holoholo.Rpc", "GetMapObjectsOutProto");
    int32_t status = get_obj_i32(out, fld(outK, "Status"));
    snprintf(buf, sizeof buf, "{\"State\":200,\"mapStatus\":%d}", status);
    return (*env)->NewStringUTF(env, buf);
}

/* StartEncounter (Encounter 102). */
JNIEXPORT jstring JNICALL
Java_com_android_jmq_impl_gamebot_GameBotNative_startEncounter(JNIEnv* env, jclass cls,
                                                               jlong encounterId,
                                                               jstring spawnpointId,
                                                               jdouble lat, jdouble lng) {
    (void)cls;
    const char* sp = (*env)->GetStringUTFChars(env, spawnpointId, NULL);
    char buf[256];
    ProtoField in[] = {
        { "EncounterId",   F_I64, (double)encounterId, NULL },
        { "SpawnpointId",  F_STR, 0, sp },
        { "PlayerLatDegrees", F_DBL, lat, NULL },
        { "PlayerLngDegrees", F_DBL, lng, NULL },
        TERMINATOR
    };
    Il2CppObject* out = rpc_call(M_ENCOUNTER, "Holoholo.Rpc", "EncounterProto", in);
    (*env)->ReleaseStringUTFChars(env, spawnpointId, sp);
    if (!out)
        return (*env)->NewStringUTF(env, "{\"State\":503,\"Msg\":\"rpc-no-pin-or-timeout\"}");
    snprintf(buf, sizeof buf, "{\"State\":200,\"encounter\":1}");
    return (*env)->NewStringUTF(env, buf);
}

/* ThrowBall (CatchPokemon 103). Devolve Status de captura p/ decisao de
 * continuar arremessando ou fugir (CatchSuccess/CatchEscape/CatchFlee). */
JNIEXPORT jstring JNICALL
Java_com_android_jmq_impl_gamebot_GameBotNative_throwBall(JNIEnv* env, jclass cls,
                                                          jlong encounterId, jint pokeball,
                                                          jstring spawnPointGuid,
                                                          jdouble reticleSize, jdouble spinModifier,
                                                          jdouble hitPosition, jboolean hitPokemon) {
    (void)cls;
    const char* guid = (*env)->GetStringUTFChars(env, spawnPointGuid, NULL);
    char buf[256];
    ProtoField in[] = {
        { "EncounterId", F_I64, (double)encounterId, NULL },
        { "Pokeball", F_INT, pokeball, NULL },
        { "SpawnPointGuid", F_STR, 0, guid },
        { "NormalizedReticleSize", F_DBL, reticleSize, NULL },
        { "SpinModifier", F_DBL, spinModifier, NULL },
        { "NormalizedHitPosition", F_DBL, hitPosition, NULL },
        { "HitPokemon", F_BOOL, hitPokemon ? 1 : 0, NULL },
        TERMINATOR
    };
    Il2CppObject* out = rpc_call(M_CATCH_POKEMON, "Holoholo.Rpc", "CatchPokemonProto", in);
    (*env)->ReleaseStringUTFChars(env, spawnPointGuid, guid);
    if (!out)
        return (*env)->NewStringUTF(env, "{\"State\":503,\"Msg\":\"rpc-no-pin-or-timeout\"}");
    Il2CppClass* outK = find_class("Holoholo.Rpc", "CatchPokemonOutProto");
    int32_t status = get_obj_i32(out, fld(outK, "Status"));
    int64_t captured = get_obj_i64(out, fld(outK, "CapturedPokemonId"));
    snprintf(buf, sizeof buf,
             "{\"State\":200,\"catchStatus\":%d,\"capturedId\":%lld}",
             status, (long long)captured);
    return (*env)->NewStringUTF(env, buf);
}

/* FleeEncounter — CatchPokemon com ShouldFlee=true (mesmo canal; o jogo
 * trata como fuga). */
JNIEXPORT jstring JNICALL
Java_com_android_jmq_impl_gamebot_GameBotNative_fleeEncounter(JNIEnv* env, jclass cls,
                                                              jlong encounterId) {
    (void)cls;
    char buf[128];
    ProtoField in[] = {
        { "EncounterId", F_I64, (double)encounterId, NULL },
        { "ShouldFlee",  F_BOOL, 1, NULL },
        TERMINATOR
    };
    Il2CppObject* out = rpc_call(M_CATCH_POKEMON, "Holoholo.Rpc", "CatchPokemonProto", in);
    if (!out)
        return (*env)->NewStringUTF(env, "{\"State\":503,\"Msg\":\"rpc-no-pin-or-timeout\"}");
    snprintf(buf, sizeof buf, "{\"State\":200,\"fled\":1}");
    return (*env)->NewStringUTF(env, buf);
}

/* SpinFort (FortSearch 101). Devolve Result (Success/InCooldownPeriod/...). */
JNIEXPORT jstring JNICALL
Java_com_android_jmq_impl_gamebot_GameBotNative_spinFort(JNIEnv* env, jclass cls,
                                                         jstring fortId,
                                                         jdouble lat, jdouble lng,
                                                         jdouble fortLat, jdouble fortLng) {
    (void)cls;
    const char* fid = (*env)->GetStringUTFChars(env, fortId, NULL);
    char buf[200];
    ProtoField in[] = {
        { "Id", F_STR, 0, fid },
        { "PlayerLatDegrees", F_DBL, lat, NULL },
        { "PlayerLngDegrees", F_DBL, lng, NULL },
        { "FortLatDegrees", F_DBL, fortLat, NULL },
        { "FortLngDegrees", F_DBL, fortLng, NULL },
        TERMINATOR
    };
    Il2CppObject* out = rpc_call(M_FORT_SEARCH, "Holoholo.Rpc", "FortSearchProto", in);
    (*env)->ReleaseStringUTFChars(env, fortId, fid);
    if (!out)
        return (*env)->NewStringUTF(env, "{\"State\":503,\"Msg\":\"rpc-no-pin-or-timeout\"}");
    Il2CppClass* outK = find_class("Holoholo.Rpc", "FortSearchOutProto");
    int32_t result = get_obj_i32(out, fld(outK, "Result"));
    int32_t xp = get_obj_i32(out, fld(outK, "XpAwarded"));
    snprintf(buf, sizeof buf, "{\"State\":200,\"fortResult\":%d,\"xp\":%d}", result, xp);
    return (*env)->NewStringUTF(env, buf);
}

/* DropItem (RecycleInventoryItem 137). */
JNIEXPORT jstring JNICALL
Java_com_android_jmq_impl_gamebot_GameBotNative_dropItem(JNIEnv* env, jclass cls,
                                                         jint item, jint count) {
    (void)cls;
    char buf[128];
    ProtoField in[] = {
        { "Item", F_INT, item, NULL },
        { "Count", F_INT, count, NULL },
        TERMINATOR
    };
    Il2CppObject* out = rpc_call(M_RECYCLE_ITEM, "Holoholo.Rpc", "RecycleItemProto", in);
    if (!out)
        return (*env)->NewStringUTF(env, "{\"State\":503,\"Msg\":\"rpc-no-pin-or-timeout\"}");
    snprintf(buf, sizeof buf, "{\"State\":200,\"dropped\":%d}", count);
    return (*env)->NewStringUTF(env, buf);
}

/* EvolvePokemon (125). */
JNIEXPORT jstring JNICALL
Java_com_android_jmq_impl_gamebot_GameBotNative_evolvePokemon(JNIEnv* env, jclass cls,
                                                              jlong pokemonId) {
    (void)cls;
    char buf[160];
    ProtoField in[] = {
        { "PokemonId", F_I64, (double)pokemonId, NULL },
        TERMINATOR
    };
    Il2CppObject* out = rpc_call(M_EVOLVE, "Holoholo.Rpc", "EvolvePokemonProto", in);
    if (!out)
        return (*env)->NewStringUTF(env, "{\"State\":503,\"Msg\":\"rpc-no-pin-or-timeout\"}");
    snprintf(buf, sizeof buf, "{\"State\":200,\"evolved\":1}");
    return (*env)->NewStringUTF(env, buf);
}

/* FavoritePokemon (SetFavoritePokemon 148). */
JNIEXPORT jstring JNICALL
Java_com_android_jmq_impl_gamebot_GameBotNative_favoritePokemon(JNIEnv* env, jclass cls,
                                                                jlong pokemonId, jboolean fav) {
    (void)cls;
    char buf[160];
    ProtoField in[] = {
        { "PokemonId", F_I64, (double)pokemonId, NULL },
        { "IsFavorite", F_BOOL, fav ? 1 : 0, NULL },
        TERMINATOR
    };
    Il2CppObject* out = rpc_call(M_SET_FAVORITE, "Holoholo.Rpc", "SetFavoritePokemonProto", in);
    if (!out)
        return (*env)->NewStringUTF(env, "{\"State\":503,\"Msg\":\"rpc-no-pin-or-timeout\"}");
    snprintf(buf, sizeof buf, "{\"State\":200,\"favorite\":%d}", fav ? 1 : 0);
    return (*env)->NewStringUTF(env, buf);
}

/* ================================================================== */
/* handle do il2cpp: soname, com fallback via /proc/self/maps          */
/* ================================================================== */
/*
 * No Android 14, o Linker Namespace Isolation esconde a libil2cpp.so (que o
 * Unity carregou no namespace da Activity principal) do lookup por soname
 * feito a partir da libfonescout.so. dlopen("libil2cpp.so", RTLD_NOLOAD)
 * retorna NULL mesmo com o jogo rodando. Mas /proc/self/maps e legivel de
 * dentro do proprio processo — entao achar o caminho absoluto real no disco
 * e dar dlopen(caminho) contorna o isolamento de namespace.
 */
static void* find_il2cpp_handle(void) {
    /* 1. tenta pelo soname primeiro (rapido, funciona em Androids antigos) */
    void* h = dlopen("libil2cpp.so", RTLD_NOLOAD);
    if (h) return h;

    /* 2. fallback: le /proc/self/maps e acha o caminho absoluto mapeado */
    FILE* fp = fopen("/proc/self/maps", "r");
    if (!fp) return NULL;

    char line[1024];
    char full_path[512];
    full_path[0] = '\0';
    while (fgets(line, sizeof line, fp)) {
        if (strstr(line, "libil2cpp.so")) {
            /* a linha termina com o caminho: ... r-xp ... /data/app/.../libil2cpp.so */
            char* path = strchr(line, '/');
            if (path) {
                path[strcspn(path, "\r\n")] = 0;
                strncpy(full_path, path, sizeof full_path - 1);
                full_path[sizeof full_path - 1] = '\0';
                break;
            }
        }
    }
    fclose(fp);

    if (full_path[0] != '\0') {
        LOGI("il2cpp real no maps: %s", full_path);
        h = dlopen(full_path, RTLD_NOLOAD);
        if (!h) h = dlopen(full_path, RTLD_NOW);
        return h;
    }
    return NULL;
}

/* ================================================================== */
/* JNI_OnLoad — bind + resolve, com retry ate o Unity carregar il2cpp   */
/* ================================================================== */
static bool try_init(void) {
    /* a libil2cpp.so ja esta no processo; resolve o handle (soname + maps) */
    void* h = find_il2cpp_handle();
    if (!h) { LOGI("libil2cpp.so ainda nao carregada"); return false; }
    if (fonescout_il2cpp_bind(&g_api, h) != 0) { LOGE("bind incompleto"); return false; }
    if (!resolve_rpc_handler()) return false;
    resolve_item_bag(); /* opcional: inventario e leitura; nao bloqueia o canal RPC */
    g_ready = true;
    LOGI("fonescout pronto");
    return true;
}

/* ================================================================== */
/* guard de SIGSEGV: runtime il2cpp pode ainda nao estar pronta        */
/* ================================================================== */
/*
 * A libil2cpp.so aparece no /proc/self/maps assim que o Unity a mmapa, mas a
 * runtime (il2cpp_init -> Domain::GetCurrent) so fica valida depois. Chamar
 * il2cpp_domain_get nessa janela dereferencia um interno NULL e derruba o
 * processo. Um injetor il2cpp precisa tolerar isso: rodamos o resolve dentro
 * de um guard com sigsetjmp/siglongjmp — se SIGSEGV ocorre DENTRO do resolve
 * (flag g_guarding), capturamos e o loop tenta de novo em 1s, sem matar o
 * jogo. Fora do guard, o handler delega ao default (crashes reais propagam).
 */
static sigjmp_buf          g_jmp;
static volatile sig_atomic_t g_guarding = 0;
static struct sigaction    g_oldsegv;

static void segv_guard_handler(int sig) {
    (void)sig;
    if (g_guarding) {
        g_guarding = 0;            /* evita reentrada while em longjmp */
        siglongjmp(g_jmp, 1);      /* volta para o try_init_guarded */
    }
    /* fora do guard: restaura comportamento default e re-crasha */
    signal(sig, SIG_DFL);
    raise(sig);
}

/* Roda try_init() sob protecao; devolve false se a runtime ainda nao pronta. */
static bool try_init_guarded(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = segv_guard_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_NODEFER;       /* permite siglongjmp limpo */
    sigaction(SIGSEGV, &sa, &g_oldsegv);

    bool ok = false;
    g_guarding = 1;
    if (sigsetjmp(g_jmp, 1) == 0) {
        ok = try_init();
    } else {
        LOGI("resolve tocou runtime nao pronta (SIGSEGV capturado); nova tentativa");
        ok = false;
    }
    g_guarding = 0;
    sigaction(SIGSEGV, &g_oldsegv, NULL);  /* restaura handler original */
    return ok;
}

/* Thread de init em background: o Unity carrega il2cpp depois do JNI_OnLoad. */
static void* init_thread(void* arg) {
    (void)arg;
    for (int i = 0; i < 180 && !g_ready; i++) { /* ~90s (cold start apos pm clear) */
        if (try_init_guarded()) break;
        sleep(1);
    }
    if (!g_ready) LOGE("init falhou apos timeout");
    return NULL;
}
JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void* reserved) {
    (void)vm; (void)reserved;
    pthread_t th;
    pthread_create(&th, NULL, init_thread, NULL);
    pthread_detach(th);
    return JNI_VERSION_1_6;
}
