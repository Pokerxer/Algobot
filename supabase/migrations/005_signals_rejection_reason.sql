-- Surface why a strategy-generated signal was not executed.
-- rejection_reason is set when executed=false and the block came from the
-- risk manager, spread filter, or other pre-execution gate (not AI veto,
-- which uses ai_reasoning).
ALTER TABLE public.signals ADD COLUMN IF NOT EXISTS rejection_reason text;
