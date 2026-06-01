-- Per-instrument evaluation of why the bot did/didn't signal each cycle.
-- One upserted row per instrument (current state only).
CREATE TABLE IF NOT EXISTS public.signal_evaluations (
  instrument     text PRIMARY KEY,
  regime         text,
  in_session     boolean,
  strategy       text,            -- 'mean_reversion' | 'momentum' | null (gated)
  status         text NOT NULL,   -- 'signal' | 'gated' | 'no_setup'
  reason         text,
  setup_distance numeric,         -- 0..1 proximity to a setup; null when gated
  detail         jsonb,
  updated_at     timestamptz DEFAULT now()
);

ALTER TABLE public.signal_evaluations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_read" ON public.signal_evaluations;
CREATE POLICY "anon_read" ON public.signal_evaluations FOR SELECT TO anon USING (true);
