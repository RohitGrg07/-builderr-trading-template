"""AI & chip momentum with a hard risk-off switch — built for Calmar.

Thesis: ride the strongest AI/chip names while the Nasdaq trend is intact; go to
cash when it isn't. Optimized for return ÷ max drawdown, not raw return.

Rules each rebalance (~weekly, or immediately on stress):
  1. RISK-OFF: QQQ below its 100-day SMA → sell everything, hold cash.
  2. CRASH BRAKE: QQQ down >5% over 5 days → same-day exit (don't wait).
  3. RISK-ON: rank NVDA, AMD, MU, MRVL, AVGO, SMH by ~3-month return; hold the
     top 4 that are still above their own 50-day SMA, equal-weight (24% each).
  4. Vol scale: if QQQ 20-day vol is elevated, cut total exposure (rest in cash).

Long-only, no leveraged ETFs, every name < 30%, gross ≤ ~1.0× (well under 1.5×).
"""
from __future__ import annotations

from statistics import mean, pstdev

AI_BASKET = ("NVDA", "AMD", "MU", "MRVL", "AVGO", "SMH")
TOP_N = 4
MOM_DAYS = 63
MOM_SKIP = 5
NAME_SMA = 50
TREND_SMA = 100
VOL_DAYS = 20
TARGET_VOL = 0.16
WEIGHT_EACH = 0.24
REBALANCE_EVERY = 5
DEAD_BAND = 0.02
BRAKE_5D = -0.05

_tick = 0
_last_rebalance = -10**9
_risk_off = False
_ANN = 252 ** 0.5


def _closes(bars: list[dict]) -> list[float]:
    return [float(b["close"]) for b in bars] if bars else []


def _sma(closes: list[float], days: int) -> float | None:
    if len(closes) < days:
        return None
    return mean(closes[-days:])


def _ret(closes: list[float], days: int, skip: int = 0) -> float | None:
    need = days + skip + 1
    if len(closes) < need:
        return None
    end = closes[-(skip + 1)]
    start = closes[-(days + skip + 1)]
    return end / start - 1.0 if start > 0 else None


def _ann_vol(closes: list[float], days: int) -> float | None:
    if len(closes) < days + 1:
        return None
    rets = [
        closes[i] / closes[i - 1] - 1.0
        for i in range(len(closes) - days, len(closes))
        if closes[i - 1] > 0
    ]
    if len(rets) < 2:
        return None
    v = pstdev(rets) * _ANN
    return v if v > 1e-6 else None


def _is_risk_off(market_state: dict) -> bool:
    qqq = _closes(market_state.get("QQQ") or [])
    if not qqq:
        return True
    sma = _sma(qqq, TREND_SMA)
    if sma is None:
        return True
    if qqq[-1] < sma:
        return True
    r5 = _ret(qqq, 5)
    if r5 is not None and r5 < BRAKE_5D:
        return True
    return False


def _exposure_scale(market_state: dict) -> float:
    vol = _ann_vol(_closes(market_state.get("QQQ") or []), VOL_DAYS)
    if vol is None or vol <= 0:
        return 0.95
    return min(0.95, TARGET_VOL / vol)


def _target_weights(market_state: dict) -> dict[str, float]:
    if _is_risk_off(market_state):
        return {}

    ranked = []
    for t in AI_BASKET:
        bars = market_state.get(t) or []
        closes = _closes(bars)
        sma = _sma(closes, NAME_SMA)
        mom = _ret(closes, MOM_DAYS, MOM_SKIP)
        if sma is None or mom is None or not closes:
            continue
        if mom > 0 and closes[-1] > sma:
            ranked.append((mom, t))
    ranked.sort(reverse=True)
    winners = [t for _, t in ranked[:TOP_N]]
    if not winners:
        return {}

    scale = _exposure_scale(market_state)
    w = min(WEIGHT_EACH, scale / len(winners))
    return {t: w for t in winners}


def decide(market_state, portfolio_state, cash):
    global _tick, _last_rebalance, _risk_off

    _tick += 1
    positions = {p["ticker"]: p for p in portfolio_state.get("positions", [])}
    last = portfolio_state.get("last_prices", {})
    equity = portfolio_state.get("cash", cash) + sum(
        p["quantity"] * last.get(t, p.get("avg_cost", 0)) for t, p in positions.items()
    )
    if equity <= 0:
        return []

    off_now = _is_risk_off(market_state)
    derisk = off_now and not _risk_off
    _risk_off = off_now

    on_cadence = _tick - _last_rebalance >= REBALANCE_EVERY
    if not on_cadence and not derisk:
        return []

    targets = _target_weights(market_state)

    orders = []
    for t, p in positions.items():
        if t not in targets and p["quantity"] > 0:
            orders.append({"ticker": t, "side": "sell", "quantity": p["quantity"]})

    for t, weight in targets.items():
        bars = market_state.get(t)
        if not bars:
            continue
        px = float(bars[-1]["close"])
        if px <= 0:
            continue
        cur = positions.get(t, {}).get("quantity", 0)
        delta = int((equity * weight - cur * px) // px)
        if abs(delta * px) < DEAD_BAND * equity:
            continue
        if delta > 0:
            orders.append({"ticker": t, "side": "buy", "quantity": delta})
        elif delta < 0 and cur > 0:
            orders.append({"ticker": t, "side": "sell", "quantity": min(abs(delta), cur)})

    if orders:
        _last_rebalance = _tick
    return orders
