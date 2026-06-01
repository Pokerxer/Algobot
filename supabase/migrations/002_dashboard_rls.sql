-- Allow the anon role (dashboard) to SELECT from all bot tables.
-- The bot writes via the service_role key which bypasses RLS.
-- These policies only grant reads — no INSERT/UPDATE/DELETE for anon.

ALTER TABLE public.bot_status         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.positions          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trades             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.signals            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.regime_snapshots   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.performance_daily  ENABLE ROW LEVEL SECURITY;

-- Drop if re-running
DROP POLICY IF EXISTS "anon_read" ON public.bot_status;
DROP POLICY IF EXISTS "anon_read" ON public.positions;
DROP POLICY IF EXISTS "anon_read" ON public.trades;
DROP POLICY IF EXISTS "anon_read" ON public.signals;
DROP POLICY IF EXISTS "anon_read" ON public.regime_snapshots;
DROP POLICY IF EXISTS "anon_read" ON public.performance_daily;

-- Grant SELECT to anon
CREATE POLICY "anon_read" ON public.bot_status        FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read" ON public.positions         FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read" ON public.trades            FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read" ON public.signals           FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read" ON public.regime_snapshots  FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read" ON public.performance_daily FOR SELECT TO anon USING (true);
