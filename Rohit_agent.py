from __future__ import annotations

# Core high-momentum asset universe
_TECH_UNIVERSE = ("NVDA", "AMD", "MU", "MRVL", "AVGO", "SMH")

# Defensive fallback universe for choppy/bear market regimes
_DEFENSIVE_UNIVERSE = ("XLP", "XLU", "XLE", "GLD")

_MARKET_BENCHMARK = "QQQ"

# Strategy Constants
_LOOKBACK_3M = 60      # ~3 months of trading data for momentum ranking
_STOCK_MA = 50         # Asset-level trend line
_MARKET_MA = 100       # Macro regime filter
_MAX_POSITIONS = 4     # 4 slots ensures a precise 25% target weight
_REBALANCE_THRESHOLD = 0.03  # 3% drift tolerance (Triggers if position hits 28%)

def decide(market_state, portfolio_state, cash):
    orders = []
    
    # 1. Macro Regime Assessment
    qqq_bars = market_state.get(_MARKET_BENCHMARK) or []
    if len(qqq_bars) < _MARKET_MA:
        return []
        
    qqq_closes = [float(b["close"]) for b in qqq_bars]
    qqq_current = qqq_closes[-1]
    qqq_ma = sum(qqq_closes[-_MARKET_MA:]) / _MARKET_MA
    
    # Determine Active Universe based on Macro Market Health
    # If tech is broken, look for defensive clusters instead of sitting completely in zero-yield cash
    is_macro_risk_on = qqq_current >= qqq_ma
    active_universe = _TECH_UNIVERSE if is_macro_risk_on else _DEFENSIVE_UNIVERSE

    # 2. Portfolio Calculations & Structure Parsing
    positions_list = portfolio_state.get("positions") or []
    current_positions = {p["ticker"]: p["quantity"] for p in positions_list if p.get("quantity", 0) > 0}
    
    total_equity = cash
    for ticker, qty in current_positions.items():
        if ticker in market_state and market_state[ticker]:
            total_equity += qty * float(market_state[ticker][-1]["close"])

    target_allocation_per_slot = total_equity / _MAX_POSITIONS

    # 3. Momentum Sifting Engine
    valid_candidates = []
    for ticker in active_universe:
        bars = market_state.get(ticker) or []
        if len(bars) < max(_LOOKBACK_3M, _STOCK_MA):
            continue
            
        closes = [float(b["close"]) for b in bars]
        current_price = closes[-1]
        stock_ma = sum(closes[-_STOCK_MA:]) / _STOCK_MA
        
        # In risk-on, enforce the strict 50-MA filter. In defensive regime, accept pure absolute momentum.
        if is_macro_risk_on and current_price <= stock_ma:
            continue
            
        return_3m = (current_price / closes[-_LOOKBACK_3M]) - 1
        if return_3m > 0:  # Only buy assets with positive absolute returns
            valid_candidates.append((ticker, return_3m, current_price))
            
    # Sort descending by momentum strength
    valid_candidates.sort(key=lambda x: x[1], reverse=True)
    target_tickers = {item[0]: item[2] for item in valid_candidates[:_MAX_POSITIONS]}

    # 4. Step 1 of Rebalancing: Liquidations and Partial Profit Shaving
    # This prevents the current #1 bot's fatal flaw: drifting past the <30% concentration limit
    for ticker, qty in current_positions.items():
        bars = market_state.get(ticker) or []
        if not bars:
            continue
        current_price = float(bars[-1]["close"])
        current_weight = (qty * current_price) / total_equity

        # Complete exit: Asset fell out of top ranking or shifted regime entirely
        if ticker not in target_tickers:
            orders.append({"ticker": ticker, "side": "sell", "quantity": qty})
            cash += (qty * current_price)
            
        # Partial Shave: Asset is still valid, but grew too large and threatens a concentration breach
        elif current_weight > (0.25 + _REBALANCE_THRESHOLD):
            target_qty = int(target_allocation_per_slot // current_price)
            shave_qty = qty - target_qty
            if shave_qty > 0:
                orders.append({"ticker": ticker, "side": "sell", "quantity": shave_qty})
                cash += (shave_qty * current_price)

    # 5. Step 2 of Rebalancing: Capital Deployments and Size Topping
    for ticker, current_price in target_tickers.items():
        if current_price <= 0:
            continue
            
        current_qty = current_positions.get(ticker, 0)
        # Recalculate target quantities safely to hit exactly 25% allocation
        target_qty = int(target_allocation_per_slot // current_price)
        
        # If position is missing or has shrunk too much below the 25% target weight
        current_weight = (current_qty * current_price) / total_equity
        if current_qty == 0 or current_weight < (0.25 - _REBALANCE_THRESHOLD):
            needed_qty = target_qty - current_qty
            if needed_qty > 0:
                spend_cash = min(needed_qty * current_price, cash)
                exec_qty = int(spend_cash // current_price)
                if exec_qty > 0:
                    orders.append({"ticker": ticker, "side": "buy", "quantity": exec_qty})
                    cash -= (exec_qty * current_price)

    return orders