"""Local self-check — runs WITHOUT the builderr engine, no network, no keys.

This is NOT the real eval (we run that centrally on hidden market data so it's
identical for everyone). It's a smoke test so you're not flying blind: it loads
your agent, feeds it synthetic daily bars, and checks that decide() returns
well-formed orders and doesn't crash. Catch the dumb bugs before you submit.

    python selfcheck.py                       # checks agent.py
    python selfcheck.py example_sector_rotation.py
"""
from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

UNIVERSE = [
    "SPY", "QQQ", "SMH", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP",
    "XLU", "XLRE", "XLC", "KRE", "JPM", "TQQQ", "SOXL", "NVDA", "MSFT", "AAPL", "META",
]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("agent", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "decide"), "your file must define decide(market_state, portfolio_state, cash)"
    return mod.decide


def _synth_bars(days: int = 120, start: float = 100.0):
    bars, px = [], start * random.uniform(0.5, 3.0)
    for i in range(days):
        px *= 1 + random.uniform(-0.02, 0.02)
        bars.append({
            "ts": f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            "open": px, "high": px * 1.01, "low": px * 0.99, "close": px, "volume": 1_000_000,
        })
    return bars


def main() -> int:
    agent_file = sys.argv[1] if len(sys.argv) > 1 else "agent.py"
    decide = _load(Path(__file__).parent / agent_file)

    market = {t: _synth_bars() for t in UNIVERSE}
    portfolio = {
        "cash": 100_000.0,
        "positions": [],
        "last_prices": {t: market[t][-1]["close"] for t in UNIVERSE},
    }

    steps, total_orders = 0, 0
    for _ in range(12):
        out = decide(market, portfolio, portfolio["cash"])
        assert isinstance(out, list), f"decide() must return a list, got {type(out).__name__}"
        for o in out:
            assert isinstance(o, dict), f"each order must be a dict, got {o!r}"
            assert {"ticker", "side", "quantity"} <= set(o), f"order missing keys: {o!r}"
            assert o["side"] in ("buy", "sell"), f"side must be 'buy' or 'sell': {o!r}"
            assert float(o["quantity"]) > 0, f"quantity must be > 0: {o!r}"
            assert o["ticker"] in UNIVERSE, f"ticker not in the universe: {o['ticker']!r}"
        total_orders += len(out)
        steps += 1

    print(f"✓ {agent_file} loaded and ran {steps} steps cleanly.")
    print(f"  {total_orders} well-formed orders emitted across the run.")
    print("  Smoke test only — real admission runs centrally on hidden market data.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"✗ FAILED: {e}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"✗ CRASHED: {e!r}")
        sys.exit(1)
