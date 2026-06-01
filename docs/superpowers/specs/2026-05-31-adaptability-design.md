# Adaptability System Design
**Date:** 2026-05-31  
**Status:** Approved  
**Scope:** Weekly-batch performance-driven parameter tuning + live edge-score lot sizing

---

## 1. Problem

The bot uses hardcoded thresholds (ADX 33, RSI 28, session windows) that never update regardless of whether they are working. Instruments that underperform continue to receive full position sizing. Instruments that outperform cannot size up automatically. A bad configuration can persist for months.

---

## 2. Solution

A weekly batch script reads 28 days of closed trades from Supabase, computes per-instrument performance metrics, and writes `config/adapted_params.json`. On the next bot restart, this file is merged on top of `settings.yaml`. Two effects:

1. **Edge multiplier** — scales lot size per instrument based on recent win rate (all instruments, even below minimum sample)
2. **Parameter tuning** — adjusts ADX threshold and RSI thresholds per instrument (only when ≥ 20 trades in window)

---

## 3. Architecture

```
bot/tools/weekly_adapt.py        standalone script — run each Sunday
bot/src/adapt/metrics.py         pure functions: metrics, edge score, param tuning
bot/config/adapted_params.json   output — bot reads on startup
bot/src/config/loader.py         updated: merges adapted_params.json into AppConfig
bot/src/risk/manager.py          updated: applies edge_multiplier to lot sizing
bot/tests/test_weekly_adapt.py   all unit + integration tests
```

No changes to strategy logic, signal generation, or MCP client.

---

## 4. Metrics

Computed per instrument from the last **28 days** of closed trades in the `trades` Supabase table.

| Metric | Formula |
|--------|---------|
| `trade_count` | count of closed trades in window |
| `win_rate` | `count(profit > 0) / trade_count` |
| `avg_win` | `mean(profit)` for winning trades |
| `avg_loss` | `mean(profit)` for losing trades |
| `expectancy` | `(win_rate × avg_win) + ((1 - win_rate) × avg_loss)` |
| `sharpe` | `mean(profits) / std(profits) × √52` |

Safe defaults returned when `trade_count == 0`: all metrics zero, edge_multiplier 1.0, adapted_params empty.

---

## 5. Edge Multiplier

Applied to every instrument regardless of sample size. Multiplies the existing `confidence_scale` in `RiskManager`. Combined effect clamped to `[0.3, 2.0]`.

| Win rate | Multiplier |
|----------|-----------|
| ≥ 0.65 | 1.30 |
| ≥ 0.55 | 1.15 |
| ≥ 0.45 | 1.00 |
| ≥ 0.35 | 0.75 |
| < 0.35 | 0.50 |

Hard bounds: `[0.5, 1.5]`.

---

## 6. Parameter Tuning

Only applied when `trade_count ≥ 20`. Maximum drift of ±2 per week. All changes respect hard bounds.

| Condition | Change | Hard bounds |
|-----------|--------|-------------|
| Momentum win_rate < 0.45 | `adx_trend_threshold` +2 | [28, 40] |
| Momentum win_rate > 0.65 | `adx_trend_threshold` −2 | [28, 40] |
| MR win_rate < 0.50 | `rsi_oversold` −2 | [20, 32] |
| MR win_rate > 0.65 | `rsi_oversold` +2 | [20, 32] |
| MR win_rate < 0.50 | `rsi_overbought` +2 | [68, 80] |
| MR win_rate > 0.65 | `rsi_overbought` −2 | [68, 80] |

Strategy assignment per instrument (used to route metrics to the right rule set):
- Momentum instruments: GBPUSDm, GBPJPYm, USDJPYm, USTECm, BTCUSDm, ETHUSDm, XAUUSDm (momentum window)
- MR instruments: EURUSDm, XAUUSDm (MR window)

---

## 7. Output File Format

`config/adapted_params.json`:

```json
{
  "generated_at": "2026-06-01T00:00:00Z",
  "window_days": 28,
  "instruments": {
    "XAUUSDm": {
      "trade_count": 18,
      "win_rate": 0.67,
      "expectancy": 14.20,
      "sharpe": 1.74,
      "edge_multiplier": 1.30,
      "adapted_params": {}
    },
    "EURUSDm": {
      "trade_count": 24,
      "win_rate": 0.42,
      "expectancy": -1.80,
      "sharpe": -0.31,
      "edge_multiplier": 0.75,
      "adapted_params": {
        "mean_reversion": { "rsi_oversold": 26, "rsi_overbought": 74 }
      }
    }
  }
}
```

---

## 8. Config Merge

`loader.py` loads `settings.yaml` first. If `adapted_params.json` exists and is valid, per-instrument `adapted_params` fields are overlaid on the base config. Fields not present in `adapted_params` retain their `settings.yaml` values.

On any file error (missing, invalid JSON, schema violation): log a WARNING and proceed with `settings.yaml` defaults only. The bot never fails to start due to a bad adaptation file.

---

## 9. RiskManager Changes

New constructor parameter: `edge_scores: dict[str, float]` (instrument → multiplier, default `{}`).

```python
edge_mult = self._edge_scores.get(signal.instrument, 1.0)
confidence_scale = 0.5 + signal.confidence          # existing: 0.5–1.5
combined = max(0.3, min(2.0, confidence_scale * edge_mult))
risk_amount = balance * (risk_per_trade_pct / 100) * combined
```

---

## 10. Weekly Script Behaviour

`bot/tools/weekly_adapt.py`:
1. Reads `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` from `.env`
2. Queries `trades` table: `closed_at >= now() - 28 days`
3. Computes metrics per instrument
4. Applies edge multiplier and parameter tuning rules
5. Writes `config/adapted_params.json`
6. Prints human-readable diff of what changed vs current `settings.yaml`

Run manually: `python tools/weekly_adapt.py`  
Optionally schedule via Windows Task Scheduler: every Sunday 00:00 UTC.

---

## 11. Tests

All in `bot/tests/test_weekly_adapt.py`. All test pure functions from `adapt/metrics.py`.

| Test | Assertion |
|------|-----------|
| `test_compute_metrics_basic` | correct win_rate, avg_win, avg_loss, expectancy from known trade list |
| `test_compute_metrics_zero_trades` | safe defaults, no divide-by-zero |
| `test_compute_metrics_all_winners` | 100% win rate handled correctly |
| `test_compute_metrics_all_losers` | 0% win rate handled correctly |
| `test_edge_multiplier_bands` | each win_rate tier → correct multiplier |
| `test_param_tuning_requires_min_sample` | < 20 trades → empty adapted_params |
| `test_param_tuning_raises_adx_on_low_win_rate` | win_rate < 0.45 → ADX +2 |
| `test_param_tuning_lowers_adx_on_high_win_rate` | win_rate > 0.65 → ADX −2 |
| `test_param_tuning_tightens_rsi_on_low_win_rate` | MR win_rate < 0.50 → rsi_oversold −2 |
| `test_param_tuning_relaxes_rsi_on_high_win_rate` | MR win_rate > 0.65 → rsi_oversold +2 |
| `test_guardrails_clamp_adx` | ADX never outside [28, 40] |
| `test_guardrails_clamp_rsi` | rsi_oversold never outside [20, 32] |
| `test_guardrails_clamp_edge_multiplier` | edge_multiplier never outside [0.5, 1.5] |
| `test_config_merge_uses_defaults_on_missing_file` | missing file → settings.yaml values intact |
| `test_config_merge_overlays_adapted_field` | adapted rsi_oversold replaces base, other fields unchanged |
| `test_risk_manager_applies_edge_multiplier` | lot size scales correctly with edge_multiplier |
| `test_risk_manager_caps_combined_scale` | confidence × edge clamped to [0.3, 2.0] |
| `test_weekly_adapt_end_to_end` | known mock trade rows → expected JSON output |
