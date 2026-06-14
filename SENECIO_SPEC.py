"""
SENECIO — REALITY-ANCHORED SPECIFICATION
========================================

IDENTITY: market_physics_allocator
NOT: price_prediction_engine, guaranteed_profit_system,
     macroeconomic_forecaster, fully_autonomous_trading_bot
CORE: survival_over_profit

ARCHITECTURE (Single Source of Truth):
    Brain:      SingleDecisionCore (institutional_core.py)
    Memory:     EventStore (event_store.py)
    Execution:  LeanExecutor (lean_executor.py)
    Authority:  1

DATA LAYER (ALLOWED ONLY):
    Binance Public, Bybit Public, Orderbook, Trade, Funding, OI
    FORBIDDEN: BCRA, INDEC, Bluelytics, Santander Macro feeds

PIPELINE: observe → classify → compress → estimate_edge →
          apply_risk → simulate_exec → record_truth → evaluate_stab

RISK: max_dd=0.12, ruin<0.05, hard_stop, capital_preservation=0.75
KILL: data_integrity_loss, liquidity_collapse, desync,
      model_reality_divergence, unexplained_vol_spike

MODE: PREDICT_ONLY — no orders, no positions, no testnet
TARGET: 500+ verified predictions before execution consideration
"""
