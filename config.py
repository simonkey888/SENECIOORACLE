"""
GLM Decision Engine v2 — Configuration

Central config for all pipeline modules.
Supports Binance testnet / sandbox / live modes.
"""

import os


class PipelineConfig:
    """Pipeline configuration with environment variable overrides."""
    
    # ── MODE ──────────────────────────────────────────────
    SIMULATION = os.getenv("GLM_SIMULATION", "true").lower() == "true"
    
    # ── EXCHANGE ──────────────────────────────────────────
    EXCHANGE_ID = os.getenv("GLM_EXCHANGE", "binance")
    API_KEY = os.getenv("GLM_API_KEY", "")
    API_SECRET = os.getenv("GLM_API_SECRET", "")
    SANDBOX = os.getenv("GLM_SANDBOX", "true").lower() == "true"
    
    # ── Binance connection modes ──────────────────────────
    # 1. Sandbox (testnet) — default
    # 2. Paper trading (real price feed, no real orders)
    # 3. Micro capital (100-200 USD)
    # 4. Full capital
    TRADING_MODE = os.getenv("GLM_TRADING_MODE", "sandbox")  # sandbox | paper | micro | live
    
    # ── DATABASE ──────────────────────────────────────────
    DB_PATH = os.getenv("GLM_DB_PATH", "glm_pipeline.db")
    
    # ── LOOP ──────────────────────────────────────────────
    LOOP_DELAY = int(os.getenv("GLM_LOOP_DELAY", "60"))
    
    # ── SYMBOL ────────────────────────────────────────────
    SYMBOL = os.getenv("GLM_SYMBOL", "BTC/USDT")
    TIMEFRAME = os.getenv("GLM_TIMEFRAME", "1h")
    
    # ── RISK LIMITS ───────────────────────────────────────
    MAX_DAILY_LOSS_PCT = float(os.getenv("GLM_MAX_DAILY_LOSS", "-5.0"))
    MAX_LEVERAGE = int(os.getenv("GLM_MAX_LEVERAGE", "5"))
    MAX_POSITION_PCT = float(os.getenv("GLM_MAX_POSITION_PCT", "0.30"))
    MAX_POSITIONS = int(os.getenv("GLM_MAX_POSITIONS", "3"))
    MAX_EXPOSURE_PCT = float(os.getenv("GLM_MAX_EXPOSURE", "0.80"))
    
    # ── DECISION THRESHOLDS ──────────────────────────────
    MIN_CONFIDENCE = float(os.getenv("GLM_MIN_CONFIDENCE", "0.65"))
    MIN_EDGE = float(os.getenv("GLM_MIN_EDGE", "0.0"))
    MAX_ENTROPY = float(os.getenv("GLM_MAX_ENTROPY", "0.75"))
    
    # ── GATE THRESHOLDS ──────────────────────────────────
    MIN_VOLUME_24H = float(os.getenv("GLM_MIN_VOLUME", "1000000"))
    MAX_SPREAD_PCT = float(os.getenv("GLM_MAX_SPREAD", "0.001"))
    MAX_OI_CHANGE_PCT = float(os.getenv("GLM_MAX_OI_CHANGE", "20.0"))
    MAX_FUNDING_PCT = float(os.getenv("GLM_MAX_FUNDING", "0.0005"))
    ANOMALY_SCORE_LIMIT = float(os.getenv("GLM_ANOMALY_LIMIT", "0.4"))
    
    # ── WATCHDOG ─────────────────────────────────────────
    MAX_RESTARTS = int(os.getenv("GLM_MAX_RESTARTS", "10"))
    WATCHDOG_COOLDOWN = int(os.getenv("GLM_WATCHDOG_COOLDOWN", "30"))
    
    @classmethod
    def get_risk_state(cls) -> dict:
        """Return default risk state from config."""
        return {
            "daily_pnl_pct": 0.0,
            "max_daily_loss_pct": cls.MAX_DAILY_LOSS_PCT,
            "cooldown_active": False,
            "open_positions": 0,
            "max_positions": cls.MAX_POSITIONS,
            "total_exposure_pct": 0.0,
            "max_exposure_pct": cls.MAX_EXPOSURE_PCT,
        }
    
    @classmethod
    def get_risk_config(cls) -> dict:
        """Return risk config for decision engine."""
        return {
            "risk_allowed": True,
            "max_leverage": cls.MAX_LEVERAGE,
            "max_position_pct": cls.MAX_POSITION_PCT,
        }
    
    @classmethod
    def get_constraints(cls) -> dict:
        """Return decision constraints."""
        return {
            "min_confidence": cls.MIN_CONFIDENCE,
            "min_edge": cls.MIN_EDGE,
            "max_entropy": cls.MAX_ENTROPY,
        }
    
    @classmethod
    def create_exchange(cls):
        """Create and return a configured CCXT exchange instance."""
        if cls.SIMULATION:
            return None
        
        try:
            import ccxt
            exchange_class = getattr(ccxt, cls.EXCHANGE_ID)
            exchange = exchange_class({
                "apiKey": cls.API_KEY,
                "secret": cls.API_SECRET,
                "sandbox": cls.SANDBOX,
                "options": {"defaultType": "future"},
            })
            if cls.SANDBOX:
                exchange.set_sandbox_mode(True)
            exchange.load_markets()
            return exchange
        except Exception as e:
            print(f"[CONFIG] Failed to create exchange: {e}")
            return None
    
    @classmethod
    def summary(cls) -> dict:
        """Return a summary of current config."""
        return {
            "mode": "SIMULATION" if cls.SIMULATION else "LIVE",
            "trading_mode": cls.TRADING_MODE,
            "sandbox": cls.SANDBOX,
            "symbol": cls.SYMBOL,
            "timeframe": cls.TIMEFRAME,
            "loop_delay": cls.LOOP_DELAY,
            "max_leverage": cls.MAX_LEVERAGE,
            "max_position_pct": cls.MAX_POSITION_PCT,
            "max_entropy": cls.MAX_ENTROPY,
            "db_path": cls.DB_PATH,
        }
