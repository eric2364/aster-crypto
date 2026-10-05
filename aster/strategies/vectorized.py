"""Causal indicator screening only. Signals feed the event engine for final validation."""
import numpy as np
import pandas as pd
from aster.strategies.base import BaseStrategy
from aster.backtest.execution import floor_step

def moving_average_signals(close, fast=8, slow=24):
    if not 0<fast<slow:raise ValueError('Require 0 < fast < slow')
    fast_ma=close.rolling(fast,min_periods=fast).mean()
    slow_ma=close.rolling(slow,min_periods=slow).mean()
    return (fast_ma>slow_ma).astype(float).where(slow_ma.notna(),0)

def screen_returns(close, weights, fee_bps=5):
    """Diagnostic close-to-close model with 1-period lag, no derivatives accounting."""
    aligned=weights.reindex_like(close).fillna(0).shift(1).fillna(0)
    pnl=(close.pct_change().fillna(0)*aligned).sum(axis=1)
    costs=aligned.diff().fillna(aligned).abs().sum(axis=1)*fee_bps/10000
    return pd.DataFrame({'gross_return':pnl,'cost':costs,'net_return':pnl-costs})

class VectorizedStrategy(BaseStrategy):
    def __init__(self, signals, allocation=.2):
        """signals indexed by candle AVAILABLE/END time, columns instrument IDs."""
        self.signals=signals;self.allocation=allocation
        if not signals.index.is_unique or not isinstance(signals.index.dtype,pd.DatetimeTZDtype):
            raise ValueError('Unique timezone-aware availability index required')
    def on_bar(self,ctx,bar):
        iid=bar['instrument_id']
        if ctx.now not in self.signals.index or iid not in self.signals:return
        value=float(self.signals.loc[ctx.now,iid])
        if not np.isfinite(value):return
        spec=ctx.instruments[iid]
        if spec.market_type=='spot':value=max(0,value)
        qty=floor_step(ctx.portfolio.venue_equity(spec.exchange)*self.allocation*abs(value)/bar['close'],spec.lot_size)
        ctx.target(iid,qty*(1 if value>=0 else -1))
