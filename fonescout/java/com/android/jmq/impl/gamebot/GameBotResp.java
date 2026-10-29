package com.android.jmq.impl.gamebot;

import com.android.jmq.base.BaseResponse;

/**
 * Resposta própria das ações de jogo — uma instância por chamada.
 *
 * O plugin usa ErrorResp (singleton) para tudo; aqui criamos instância nova
 * porque o ZMQ REP pode ter múltiplas requisições em voo e o singleton
 * compartilharia o mesmo objeto entre elas (race em Action/State/data).
 */
public class GameBotResp extends BaseResponse<String> {

    public GameBotResp(String action, int state, String data) {
        this.Action = action;
        this.State = state;
        this.data = data;
    }
}
