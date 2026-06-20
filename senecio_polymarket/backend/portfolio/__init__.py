"""
SENECIO ORACLE — ACT XXV: Portfolio subpackage
================================================

Institutional execution layer built on top of the existing oracle pipeline.
Does NOT touch:
  - prediction model (predict_only.py)
  - feature engineering (institutional_core.py compress_features)
  - signal generation (institutional_core.py produce_action)
  - verifier (oracle_runner.py _verify_pending_outcomes / _backfill_bogus_outcomes)

Public API:
    from .portfolio.coordinator import PortfolioCoordinator
    coordinator = PortfolioCoordinator()
    coordinator.start()
    await coordinator.ingest_prediction(prediction_dict, last_price=...)
"""
from .portfolio_engine import PortfolioEngine, TradeProposal, PortfolioState
from .risk_kernel import RiskKernel, RiskDecision, KernelState, VolRegime
from .execution_engine import ExecutionEngine, Order, Fill, Position, OrderStatus, ExitReason
from .trade_journal import TradeJournal
from .portfolio_analytics import PortfolioAnalytics
from .shadow_live import ShadowLive, ShadowTrade
from .live_gate import LiveGate, GateStatus
from .coordinator import PortfolioCoordinator

__all__ = [
    "PortfolioEngine",
    "TradeProposal",
    "PortfolioState",
    "RiskKernel",
    "RiskDecision",
    "KernelState",
    "VolRegime",
    "ExecutionEngine",
    "Order",
    "Fill",
    "Position",
    "OrderStatus",
    "ExitReason",
    "TradeJournal",
    "PortfolioAnalytics",
    "ShadowLive",
    "ShadowTrade",
    "LiveGate",
    "GateStatus",
    "PortfolioCoordinator",
]

VERSION = "ACT-XXV-hedge-fund-transition"
