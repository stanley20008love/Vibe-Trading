"""Global equity (US / HK) backtest engine.

Market rules:
  US:
    - T+0, long/short allowed
    - Zero commission (retail brokers)
    - Fractional shares supported (round to 0.01)
    - Low slippage (high liquidity)
  HK:
    - T+0, long/short allowed
    - Stamp tax 0.13% bilateral + levies
    - Lot-size rounding (simplified to 100 shares)
    - Higher slippage than US
"""

from __future__ import annotations

import pandas as pd

from backtest.engines.base import BaseEngine


class GlobalEquityEngine(BaseEngine):
    """US / HK equity engine, selected by *market* parameter.

    Config keys:
      - slippage_us: default 0.001
      - slippage_hk: default 0.002
      - hk_stamp_tax: default 0.0013 (0.13% bilateral)
      - hk_commission: default 0.0005 (万5)
      - us_sec_fee: default 0.0000279 (per dollar of sale proceeds)
      - short_borrow_rate: default 0.01 (1% annual for US/HK shorts)
      - hk_levy: default 0.0000565 (SFC + FRC)
      - hk_settlement: default 0.00002 (CCASS)
    """

    def __init__(self, config: dict, market: str = "us"):
        config = {**config, "leverage": config.get("leverage", 1.0)}
        super().__init__(config)
        self.market = market

        # US defaults
        self.slippage_us: float = config.get("slippage_us", 0.001)
        # HK defaults
        self.slippage_hk: float = config.get("slippage_hk", 0.002)
        self.hk_stamp_tax: float = config.get("hk_stamp_tax", 0.0013)
        self.hk_commission: float = config.get("hk_commission", 0.0005)
        self.hk_levy: float = config.get("hk_levy", 0.0000565)
        self.hk_settlement: float = config.get("hk_settlement", 0.00002)
        # US SEC fee (per dollar of sale proceeds)
        self.us_sec_fee: float = config.get("us_sec_fee", 0.0000279)
        # Short selling borrow cost (annual rate, charged daily)
        self.short_borrow_rate: float = config.get("short_borrow_rate", 0.01)

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """US/HK: T+0, both directions allowed."""
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """US: fractional shares (0.01). HK: 100-share lots."""
        if self.market == "hk":
            return max(int(raw_size / 100) * 100, 0)
        return round(max(raw_size, 0.0), 2)

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """US: SEC fee on sales. HK: stamp tax + levies."""
        if self.market == "hk":
            notional = size * price
            comm = notional * self.hk_commission       # broker commission
            comm += notional * self.hk_stamp_tax       # stamp tax bilateral
            comm += notional * self.hk_levy            # SFC + FRC levies
            comm += notional * self.hk_settlement      # CCASS settlement
            return comm
        # US: SEC fee on sale proceeds only
        if not is_open:
            return size * price * self.us_sec_fee
        return 0.0

    def apply_slippage(self, price: float, direction: int) -> float:
        """US: moderate slippage. HK: higher slippage."""
        rate = self.slippage_hk if self.market == "hk" else self.slippage_us
        return price * (1 + direction * rate)

    def on_bar(self, symbol: str, bar: pd.Series, timestamp: pd.Timestamp) -> None:
        """Charge short selling borrow cost daily for US/HK short positions."""
        pos = self.positions.get(symbol)
        if pos is None or pos.direction != -1:
            return
        # Daily borrow cost: annual_rate / 252 * notional
        daily_borrow = self.short_borrow_rate / 252.0 * pos.size * float(bar.get("close", pos.entry_price))
        self.capital -= daily_borrow
