-- Add unique constraint on trades.ticket to prevent duplicate records
-- when multiple bot instances run simultaneously or MCP reconnects trigger re-detection.
ALTER TABLE trades ADD CONSTRAINT trades_ticket_unique UNIQUE (ticket);
