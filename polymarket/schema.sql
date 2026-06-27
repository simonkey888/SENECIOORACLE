-- H-010 Polymarket Edge Detection — Supabase table schema
-- Execute manually via Supabase dashboard SQL editor

CREATE TABLE IF NOT EXISTS polymarket_markets (
    id          BIGSERIAL PRIMARY KEY,
    market_id   TEXT NOT NULL,
    question    TEXT,
    p_yes       NUMERIC(6,4),         -- YES probability at signal time
    p_no        NUMERIC(6,4),          -- NO probability at signal time
    volume_usd  NUMERIC(14,2),         -- Volume at snapshot time
    end_date    DATE,                  -- Market resolution date
    signal      TEXT DEFAULT 'FADE_YES',
    event_title TEXT,
    snapshot_utc TIMESTAMPTZ NOT NULL, -- When we observed this signal
    fee_bps     INTEGER DEFAULT 1000,  -- Taker fee in basis points
    outcome     TEXT,                  -- 'WIN' or 'LOSS' (for our signal) after resolution
    pnl_net     NUMERIC(10,4),         -- Net PnL per unit bet (after fees)
    resolved_at TIMESTAMPTZ,           -- When the market resolved
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Index for dedup: one signal per market_id per snapshot date
CREATE UNIQUE INDEX IF NOT EXISTS idx_pm_markets_dedup
    ON polymarket_markets (market_id, snapshot_utc);

-- Enable RLS
ALTER TABLE polymarket_markets ENABLE ROW LEVEL SECURITY;

-- Allow INSERT + SELECT with anon key (same pattern as oracle_predictions)
CREATE POLICY "Allow anon insert" ON polymarket_markets
    FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow anon select" ON polymarket_markets
    FOR SELECT USING (true);
CREATE POLICY "Allow anon update" ON polymarket_markets
    FOR UPDATE USING (true);
