# Work Items

| ID | title | role | targets | surface | status | evidence | notes |
|----|-------|------|---------|---------|--------|----------|-------|
| WI-001 | Scope/auth + case init | lead | case | process | done | E-001 | auth granted (own_system) |
| WI-002 | RE do plugin (ZMQ/ações/hooks/config) | lead | pokemon_custom.apk assets/plugin.apk | static jadx+strings | done | E-001 | 7 ações só-de-localização; offsets il2cpp mapeados |
| WI-003 | Bootstrap ferramentas (jadx/frida/Redux) | lead | host | toolchain | done | E-001 | redux dump v39 em curso (bg) |
| WI-004 | Stack PC: pogolink + bot_brain + config | lead | PC | zmq | done | E-002 | malha 4D; probe ao vivo OK |
| WI-005 | Dump il2cpp v39 (Redux) → mapa de métodos | lead | libil2cpp.so + global-metadata.dat | static | done | E-003 | stub C# 1.14M linhas; metadata v390 |
| WI-006 | Selecionar classes/métodos-alvo do jogo | lead+spec | out-redux | static | done | E-003 | SendRpc(102/103/101/137/125/148/106); IItemBag p/ inventário |
| WI-007 | libfonescout.so (API il2cpp runtime) | spec-native (ida-reverse/r2) | plugin | native arm64 | done | E-003 | bind dlsym + Zenject resolve; 10 JNIEXPORT; sem root; 0.433.1 |
| WI-008 | Novas ações BaseRequest + registro addExtraFunc | spec-apk | plugin classes.dex | smali/kotlin | done | E-003 | 9 ações gamebot; registro via smali patch no JMQServer.startJar |
| WI-009 | Repack plugin.apk → pokemon_custom.apk + assinatura | lead | APK | rebuild/sign | done | E-003 | build.sh; classes3.dex (multidex) + libfonescout.so; keystore própria |
| WI-010 | Teste em dispositivo + calibração de timing | lead+user | Infinix X6711 | live | pending | | calibrar kRpcPins (WI-010) + ranges do mesh contra telemetria |

## Coverage
- [x] Recon/analysis complete for in_scope assets
- [ ] Critical/High candidates triaged (or N/A for pure RE)
- [x] Validated findings have Evidence (E-*)
- [x] Path documented (attack/call/solve)
- [x] Timeline continuous across major phases
- [ ] Report via docs-generator
- [ ] field-journal anonymized

## Refs
- skills/ops/timeline-workitem.md
- skills/ops/evidence-finding-path.md
