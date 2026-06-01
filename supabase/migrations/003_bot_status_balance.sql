-- Add live balance and equity fields to bot_status so the dashboard
-- can show real-time account metrics without waiting for performance_daily.
ALTER TABLE public.bot_status
  ADD COLUMN IF NOT EXISTS balance   NUMERIC,
  ADD COLUMN IF NOT EXISTS equity    NUMERIC,
  ADD COLUMN IF NOT EXISTS float_pnl NUMERIC;
