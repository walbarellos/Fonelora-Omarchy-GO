/*
 * fonescout/il2cpp_api.h — API il2cpp resolvida em runtime via dlsym.
 *
 * Por que dlsync e nao link estatico: a libil2cpp.so so existe dentro do
 * processo do jogo, carregada pelo Unity. Nosso .so carrega depois e resolve
 * os simbolos pelo nome. Assim nao precisamos do dump na hora do build —
 * apenas dos nomes de classe/metodo, que sao estaveis para a versao pinada.
 *
 * Os typedefs sao minimos: apenas o que fonescout.c usa.
 */
#ifndef FONESCOUT_IL2CPP_API_H
#define FONESCOUT_IL2CPP_API_H

#include <stdint.h>
#include <stdbool.h>

/* ---- tipos opacos (layout nao importa; tratamos como ponteiro cego) ---- */
typedef struct Il2CppDomain      Il2CppDomain;
typedef struct Il2CppAssembly    Il2CppAssembly;
typedef struct Il2CppImage       Il2CppImage;
typedef struct Il2CppClass       Il2CppClass;
typedef struct Il2CppObject      Il2CppObject;
typedef struct Il2CppString      Il2CppString;
typedef struct Il2CppType        Il2CppType;
typedef struct MethodInfo        MethodInfo;
typedef struct FieldInfo         FieldInfo;
typedef struct Il2CppException   Il2CppException;
typedef union  Il2CppValue       Il2CppValue;

/* ---- assinaturas das funcoes que usamos (IL2CPP_API_FUNC equivalents) ---- */
typedef Il2CppDomain*  (*il2cpp_domain_get_t)(void);
typedef const Il2CppAssembly** (*il2cpp_domain_get_assemblies_t)(const Il2CppDomain*, size_t* count);
typedef const Il2CppImage* (*il2cpp_assembly_get_image_t)(const Il2CppAssembly*);
typedef Il2CppClass*   (*il2cpp_class_from_name_t)(const Il2CppImage*, const char* namespaze, const char* name);
typedef const MethodInfo* (*il2cpp_class_get_method_from_name_t)(Il2CppClass*, const char* name, int argsCount);
typedef const FieldInfo*  (*il2cpp_class_get_field_from_name_t)(Il2CppClass*, const char* name);
typedef size_t         (*il2cpp_field_get_offset_t)(const FieldInfo*);
typedef void           (*il2cpp_field_get_value_t)(Il2CppObject*, const FieldInfo*, void* value);
typedef void           (*il2cpp_field_set_value_t)(Il2CppObject*, const FieldInfo*, void* value);
typedef Il2CppObject*  (*il2cpp_field_get_value_object_t)(const FieldInfo*, Il2CppObject*);
typedef Il2CppObject*  (*il2cpp_object_new_t)(const Il2CppClass*);
typedef Il2CppObject*  (*il2cpp_runtime_invoke_t)(const MethodInfo*, void* obj, void** params, Il2CppException** exc);
typedef Il2CppString*  (*il2cpp_string_new_t)(const char*);
/* il2cpp_string_to_utf8 NAO e exportado em Unity 6000.6.0a6 (0.433.1). A API
 * oficial de leitura e string_chars (UTF-16) + string_length; a conversao
 * para UTF-8 e feita por il2cpp_str_to_utf8() em fonescout.c. */
typedef int32_t        (*il2cpp_string_length_t)(Il2CppString*);
typedef const uint16_t*(*il2cpp_string_chars_t)(Il2CppString*);
typedef const Il2CppType* (*il2cpp_class_get_type_t)(const Il2CppClass*);
typedef Il2CppObject*  (*il2cpp_type_get_object_t)(const Il2CppType*);
typedef const char*    (*il2cpp_class_get_name_t)(const Il2CppClass*);
typedef const char*    (*il2cpp_class_get_namespace_t)(const Il2CppClass*);
typedef const MethodInfo* (*il2cpp_class_get_methods_t)(Il2CppClass*, void** iter);

/* ---- bundle de ponteiros resolvido uma vez ---- */
typedef struct Il2CppApi {
    il2cpp_domain_get_t                domain_get;
    il2cpp_domain_get_assemblies_t     domain_get_assemblies;
    il2cpp_assembly_get_image_t        assembly_get_image;
    il2cpp_class_from_name_t           class_from_name;
    il2cpp_class_get_method_from_name_t class_get_method_from_name;
    il2cpp_class_get_field_from_name_t class_get_field_from_name;
    il2cpp_field_get_offset_t          field_get_offset;
    il2cpp_field_get_value_t           field_get_value;
    il2cpp_field_set_value_t           field_set_value;
    il2cpp_field_get_value_object_t    field_get_value_object;
    il2cpp_object_new_t                object_new;
    il2cpp_runtime_invoke_t            runtime_invoke;
    il2cpp_string_new_t                string_new;
    il2cpp_string_length_t             string_length;
    il2cpp_string_chars_t              string_chars;
    il2cpp_class_get_type_t            class_get_type;
    il2cpp_type_get_object_t           type_get_object;
    il2cpp_class_get_name_t            class_get_name;
    il2cpp_class_get_namespace_t       class_get_namespace;
    il2cpp_class_get_methods_t         class_get_methods;
} Il2CppApi;

/* Resolve todos os simbolos de `handle` (dlopen da libil2cpp). Retorna 0 ok. */
int  fonescout_il2cpp_bind(Il2CppApi* api, void* handle);
bool fonescout_il2cpp_ready(void);
Il2CppApi* fonescout_il2cpp(void);

#endif /* FONESCOUT_IL2CPP_API_H */
