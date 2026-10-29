package com.android.jmq.impl.gamebot;

import com.android.jmq.base.BaseRequest;
import com.android.jmq.base.BaseResponse;
import org.json.JSONObject;

/**
 * Base para as ações de jogo que delegam à lib nativa libfonescout.so.
 *
 * Segue o mesmo contrato do plugin: cada ação tem um ACTION (chave no
 * RequestConfig/addExtraFunc) e devolve BaseResponse. Aqui o trabalho real
 * (montar proto + SendRpc via il2cpp) acontece na nativa; esta classe só
 * extrai os parâmetros do JSON e repassa o envelope de volta ao ZMQ.
 *
 * Usa org.json (nativo do Android) em vez do fastjson do plugin: mesma API
 * para os campos que usamos, e remove a dependência de compilá-lo junto.
 *
 * Herança de BaseRequest respeita o LruCache do RequestParser (uma instância
 * por classe, reusada entre chamadas) — por isso não guardamos estado entre
 * execute()s.
 */
public abstract class NativeGameRequest extends BaseRequest {

    /** Chave da ação (espelha o ACTION que a subclasse declara). */
    protected abstract String action();

    /** Subclasses constroem a chamada nativa a partir dos params. */
    protected abstract String callNative(JSONObject p);

    @Override
    public BaseResponse execute() {
        String act = action();
        JSONObject p;
        try {
            p = new JSONObject(this.mRequest);
        } catch (Exception e) {
            return new GameBotResp(act, 400, "bad-request-json");
        }
        String nativeJson;
        try {
            nativeJson = callNative(p);
        } catch (Throwable t) {
            return new GameBotResp(act, 500, "native-threw:" + t);
        }
        if (nativeJson == null || nativeJson.isEmpty()) {
            return new GameBotResp(act, 500, "native-empty");
        }
        try {
            JSONObject o = new JSONObject(nativeJson);
            int state = o.optInt("State", 500);
            String msg = o.optString("Msg", null);
            // Reusa o envelope: State 200 => sucesso; senão repassa o código
            // e a mensagem da nativa (que diagnostica bind/resolve/invoke).
            return new GameBotResp(act, state,
                    (msg != null && !msg.isEmpty()) ? msg : o.toString());
        } catch (Exception e) {
            return new GameBotResp(act, 502, "native-bad-json:" + nativeJson);
        }
    }
}
