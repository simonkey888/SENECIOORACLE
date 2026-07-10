# Santander Control-Plane Adoption Boundary

**Fecha**: 2026-07-10
**Autor**: GLM-5.2
**Estado**: DOCUMENTO DE ADOPCIÓN

## 1. Patrones que se adoptan

| Patrón Santander | Adopción SENECIO |
|------------------|------------------|
| MarketState | ScanStateSnapshot |
| Source health | SourceHealthRegistry |
| Lifecycle | PredictionLifecycleStore |
| Invariants | InvariantMonitor |
| Paper executor | ShadowExecution |
| Monitor | ControlPlaneMonitor |
| Stress modes | ExecutionStressScenarios |
| Provenance | EvidenceProvenance |

## 2. Patrones que se rechazan

| Patrón Santander | Razón de rechazo |
|------------------|------------------|
| One score per asset | No aplica a H-011 (mercados binarios, no portfolio) |
| REAL generalizado | Prohibido en H-011 V3 (PAPER_ONLY) |
| Métricas con n=0 | Deben ser null, no 0.50% o 100% |
| NAV sin fills | Prohibido (realized_pnl = null sin fills reales) |
| Pesos macro | No aplica (no hay portfolio multi-asset) |
| VaR/Sharpe sintéticos | No aplica sin datos de resolución |
| Etiquetas "REAL" en proyecciones | Prohibido |
| Retornos mensuales proyectados | No aplica |
| Recomendaciones de inversión | No aplica |
| FCI/PF/CEDEARs | No aplica |

## 3. Archivos de SENECIO que se modificarán

| Archivo | Cambio |
|---------|--------|
| `polymarket/h011_v3_pipeline.py` | Integrar SourceHealth, Provenance, Lifecycle, Invariants |
| `polymarket/vwap_detector_v2.py` | Dispatcher ya implementado (no changes) |
| `.github/workflows/h011-integrity.yml` | Extender con tests de control plane |

## 4. Archivos nuevos que se crearán

```
polymarket/control_plane/
├── __init__.py
├── semantic_status.py      # N1
├── source_health.py         # N2
├── provenance.py            # N3
├── state_snapshot.py        # N4
├── lifecycle_store.py       # N5
├── invariant_monitor.py     # N6
├── drift_monitor.py         # N7
├── alert_engine.py          # N8
├── stress_scenarios.py      # N9
└── __init__.py

polymarket/dashboard_v3.py   # N10+N11
polymarket/templates/dashboard_v3.html  # N11

tests/control_plane/          # N12
```

## 5. Ambigüedades semánticas observadas

1. "REAL" aparecía junto a STALE, PARTIAL_FALLBACK, SIMULADO, proyecciones, n=0
2. "VERIFIED" no distinguía entre estructura verificada y ejecución verificada
3. "BALANCE" mezclaba estimaciones VWAP con fills reales
4. n=0 producía métricas numéricas (Brier=0.0000, hit_rate=50%)
5. Fallback silencioso de V3→V2

## 6. Cómo se evita duplicar EvidenceState

`EvidenceState` (existente) representa conocimiento y validez de una evidencia individual.
`SemanticStatus` (N1, nuevo) representa dimensiones operativas ortogonales.
No hay jerarquía entre ellos — son complementarios.

## 7. Compatibilidad con registros V3

Los registros V3 existentes (`h011-v3-record-v1`) se preservan.
Los nuevos campos de control plane se agregan como sección opcional `control_plane` en el snapshot, no en el record individual.

## 8. Cómo se evita importar lógica financiera de Santander

- No se importa ningún archivo del Oráculo Santander
- No se copian fórmulas de VaR, Sharpe, PF, FCI
- No se usan etiquetas "REAL" en ningún contexto
- No se muestran balances, NAV, ni retornos proyectados
- El control plane es puramente observacional: source health, provenance, lifecycle, invariants
