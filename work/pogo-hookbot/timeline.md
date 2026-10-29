# Timeline (append-only)

## 2026-10-28T21:02:14-05:00 | lead | init
- action: case-init
- command_or_ref: skills/scripts/case-init.sh
- result_summary: case directory created; scope ready_for_act=true
- artifacts: [scope.md, workitems.md]
- evidence_ids: []
- decision_delta: [case_initialized]
- carry_forward_refs: [scope.md]
- next: open PRIMARY SKILL.md and ACT within scope

## 2026-10-28T21:05-21:40-05:00 | lead | triage+build
- action: plugin RE completo + bootstrap ferramentas + stack PC
- command_or_ref: jadx 1.5.6 (~/tools), frida-tools 17.24.3 (pipx), Il2CppInspectorRedux 2026.2, strings mining, adb live probe
- result_summary: plugin mapeado (ZMQ REP 7878, 7 ações só-de-localização, hooks Dobby por offsets il2cpp em configinfo_64.txt); PC stack validada no dispositivo real; dump metadata v39 em curso
- artifacts: [pogolink.py, bot_brain.py, bot_config.json, walk_loop.py(patch), evidence/E-001, evidence/E-002]
- evidence_ids: [E-001, E-002]
- decision_delta: [extensao_via_il2cpp_api_sem_root, ui_virtual_como_template_de_timing, malha_4d_fingerprints]
- carry_forward_refs: [evidence/E-001-plugin-architecture.md]
- next: concluir dump Redux (v39) → extrair RVAs de encontro/giro/inventário/evolução → desenhar libfonescout.so + novas ações BaseRequest → repack plugin.apk

## 2026-10-28T21:45-22:10-05:00 | lead+spec | dump concluído + mapa de alvos
- action: WI-005 dump Redux finalizado (332MB out) + WI-006 extração de alvos do stub C#
- command_or_ref: Il2CppInspectorRedux `process` (bg sh_18579a510001naiH61PMhkwIS7); grep/awk sobre il2cpp.cs
- result_summary: stub C# 1.141.013 linhas gerado (metadata v390, Unity 6000.6.0a6). Achado central: canal RPC único IRpcHandler.SendRpc(int method, InProto); enum Holoholo.Rpc.Method completo (Encounter=102, CatchPokemon=103, FortSearch=101, RecycleInventoryItem=137, Evolve=125, Favorite=148, GetMapObjects=106, Release=112); layout de campo de todos os protos-alvo extraído; IItemBag resolvido via Zenject ProjectContext para inventário sem decodificar proto (proto de inventário usa oneof ByteString).
- artifacts: [evidence/E-003.md, workitems.md(update)]
- evidence_ids: [E-003]
- decision_delta: [injecao_via_SendRpc_nao_via_UI, inventario_via_IItemBag_nao_proto, resolve_zenject_nao_genérico]
- carry_forward_refs: [evidence/E-003.md]
- next: WI-007 libfonescout.so (resolve il2cpp runtime, pin 0.433.1) + WI-008 novas ações BaseRequest no plugin → WI-009 repack/assinatura → WI-010 calibragem no Infinix

## 2026-10-28T22:10-22:35-05:00 | lead+spec | implementação + build
- action: WI-007 libfonescout.so + WI-008 ações de jogo + WI-009 repack/assinatura
- command_or_ref: NDK r27c aarch64-linux-android31-clang; javac+jdk21+d8 (build-tools 34); apktool 2.11.1; zipalign+apksigner; build.sh
- result_summary: libfonescout.so (arm64, 14.8KB) compilada limpa: bind dlsym de 18 símbolos il2cpp + resolve Zenject não-genérico + poll de Promise<T> sem delegate + 10 funções JNI exportadas. 13 classes Java (NativeGameRequest base + 9 ações + GameBotActions.register + GameBotResp por-chamada) → classes3.dex (7.1KB, org.json nativo). Registro via smali patch no JMQServer.startJar. Repack completo: classes3.dex + libfonescout.so injetados no plugin.apk (multidex nativo, sem baksmali; BaseRequest/Response só como type-ref, sem duplicata), assets/plugin.apk trocado, keystore própria fonescout.keystore. Saída: build/out/pokemon_custom_fonescout.apk (186MB), assinada e verificada. build.sh reproduzível de 6 passos.
- artifacts: [fonescout/native/*, fonescout/java/*, fonescout/build.sh, fonescout/build/out/pokemon_custom_fonescout.apk, evidence/E-004.md, workitems.md(update)]
- evidence_ids: [E-004]
- decision_delta: [multidex_classes3_sem_baksmali, orgjson_nativo_sem_fastjson, keystore_propria_requiere_uninstall, kRpcPins_pendente_wi010]
- carry_forward_refs: [evidence/E-004.md]
- next: WI-010 instalar no Infinix (uninstall+install), validar {"Action":"Status"} → State=200/il2cpp=1/rpchandler=1, pinar kRpcPins por par de proto, calibrar malha de timing, testar ações ao vivo; depois relatório (docs-generator) + commit
