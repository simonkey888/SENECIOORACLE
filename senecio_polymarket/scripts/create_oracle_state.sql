-- SENECIO ORACLE — ACT-XXXII Fix3: oracle_state table
-- Run this in the Supabase Dashboard SQL Editor to ENABLE verifier checkpoints.
-- Until this is run, oracle_verifier.py runs WITHOUT checkpoint (graceful fallback).
--
-- After running, the verifier will:
--   1. On startup: load last checkpoint (last_resolved_id, cycles_run, last_cycle_at)
--   2. After each cycle: upsert new checkpoint
-- This means a crash mid-cycle never loses state — the next restart picks up
-- from the last successfully patched row id.

CREATE TABLE IF NOT EXISTS public.oracle_state (
    key         text        PRIMARY KEY,
    value       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.oracle_state ENABLE ROW LEVEL SECURITY;

-- Anon key can read state (needed for verifier to load checkpoint on start)
DROP POLICY IF EXISTS "anon_read_oracle_state"  ON public.oracle_state;
CREATE POLICY "anon_read_oracle_state"
  ON public.oracle_state FOR SELECT
  TO anon USING (true);

-- Anon key can insert (upsert via Prefer: resolution=merge-duplicates)
DROP POLICY IF EXISTS "anon_insert_oracle_state" ON public.oracle_state;
CREATE POLICY "anon_insert_oracle_state"
  ON public.oracle_state FOR INSERT
  TO anon WITH CHECK (true);

-- Anon key can update (in case verifier uses PATCH path)
DROP POLICY IF EXISTS "anon_update_oracle_state" ON public.oracle_state;
CREATE POLICY "anon_update_oracle_state"
  ON public.oracle_state FOR UPDATE
  TO anon USING (true) WITH CHECK (true);

-- Optional: make the table visible in Supabase Studio
COMMENT ON TABLE public.oracle_state IS
  'SENECIO Oracle verifier checkpoint (ACT-XXXII Fix3). Key=verifier_state, value={last_resolved_id, cycles_run, last_cycle_at, last_summary}.';
