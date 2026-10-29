package com.android.jmq.impl;

import android.content.Context;
import com.android.jmq.base.BaseRequest;

/**
 * Stub SOMENTE-COMPILAÇÃO de RequestParser (o real vive no dex do plugin).
 *
 * Espelha exatamente os membros que GameBotActions usa (construtor + addExtraFunc)
 * para o javac validar as assinaturas. Este arquivo NAO entra no dex final —
 * em runtime quem roda e o RequestParser original do plugin, que ja contem
 * estas mesmas assinaturas (ver E-001). Mantenha em sincronia com o plugin.
 */
public class RequestParser {
    public RequestParser(Context context, int cacheSize) {}
    public RequestParser addExtraFunc(String action, Class<? extends BaseRequest> cls) {
        return this;
    }
}
