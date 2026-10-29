# fonescout — lib JNI arm64 que aciona ações de jogo via API il2cpp em runtime.
# Cross-compile com o NDK r27c (ANDROID_NDK_HOME). Sem dependência externa:
# só JNI (nativo no NDK) + dl + log.
cmake_minimum_required(VERSION 3.18)
project(fonescout C)

# Só arm64: o aparelho alvo (Infinix X6711) e arm64-v8a e o jogo pinado e 64-bit.
if(NOT ANDROID_ABI STREQUAL "arm64-v8a")
    message(FATAL_ERROR "fonescout so suporta arm64-v8a (alvo: Infinix X6711)")
endif()

add_library(fonescout SHARED
    fonescout.c)

# dl (dlopen/dlsym na libil2cpp) e log (android_log_print). pthread vem do libc.
target_link_libraries(fonescout
    dl
    log)

target_compile_options(fonescout PRIVATE
    -O2
    -fvisibility=hidden       # só exporta JNI_OnLoad + JNIEXPORT
    -Wall -Wextra)

# Endurecimento basico coerente com "nao chama atencao": strip no build.
set_target_properties(fonescout PROPERTIES
    LINK_FLAGS "-s")
