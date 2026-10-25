# Decision date: {date} (after market close)
Account: equity ${equity:.2f}, cash ${cash:.2f}. Starting capital $1000. Long-only, no leverage, no shorting.
Orders execute at the NEXT trading day's OPEN. Costs: 0.05% per side. Next review is in about {step} trading days.

## Current positions
{positions}

## Universe snapshot (computed only from bars up to and including {date}; lookback {lookback} daily bars; split-adjusted)
{snapshot}

Indicator and Volume Profile guide:
- trend: UPTREND = above SMA50 and SMA200; DOWNTREND = below SMA50 but above SMA200; BREAKDOWN = below SMA200 or below prior swing low.
- poc = Point of Control (price level with peak traded volume; institutional magnet and major support/pivot).
- hvn_sup = nearest High Volume Node support below current price.
- sup_dist = distance of close above nearest volume/60-bar support; vol_ratio = today's volume / 20-bar average volume.
- CONTINUATION = close near 20-bar high with volume expansion (vol_ratio >= 1.25) breaking above consolidation.
- PULLBACK = UPTREND pullback into SMA20/50 or HVN/POC volume support on dry volume with bounce confirmation.
- REVERSAL = test/sweep of major POC or 60-bar support with heavy volume absorption (vol_ratio >= 1.4) and bounce.

## Detected setups (mechanical; computed from bars <= {date})
{setups}

## Last {recent} daily closes per ticker (oldest -> newest)
{recent_closes}

## Task
Decide the TARGET portfolio weights (fraction of total equity, 0..1 each, sum <= 1; remainder is cash) for the next period.
1. Cash is an active defensive position: hold 50-100% cash when broad market / universe conditions are in BREAKDOWN/DOWNTREND.
2. Focus on leaders in Stage 2 UPTREND displaying confirmed CONTINUATION, PULLBACK, or REVERSAL setups.
3. Hold winners: Do NOT micro-trim winning positions just because their weight appreciated. Let winners run!
4. Exit rules: Exit names that hit trailing stops, break below SMA50, or reach extreme overbought resistance (RSI > 85).
5. Dynamic stops: Specify protective stops (stop_pct, 4..15) based on ATR volatility or support structure.

Return ONLY this JSON:
{{"market_view": "<2-3 sentences>", "targets": {{"TICKER": {{"weight": 0.25, "stop_pct": 8.0}}}}, "rationale": "<short>"}}
Tickers omitted are targeted at 0. Allowed tickers: {tickers}.
