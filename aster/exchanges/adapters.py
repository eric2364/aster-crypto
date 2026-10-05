"""Offline normalization adapters. Fee/spec values must be supplied from dated venue metadata."""
import pandas as pd
from aster.backtest.models import Instrument

class ExchangeAdapter:
    name = 'generic'
    def instrument(self, symbol, market_type='spot', **kwargs):
        return Instrument(f'{self.name}:{market_type}:{symbol}', self.name, symbol, market_type, **kwargs)
    def candles(self, rows, instrument_id, duration_seconds):
        """Normalize vendor [start_ms, open, high, low, close, base_volume, ...]."""
        df = pd.DataFrame([r[:6] for r in rows], columns=['timestamp','open','high','low','close','volume'])
        df.timestamp = pd.to_datetime(pd.to_numeric(df.timestamp), unit='ms', utc=True)
        df['instrument_id'] = instrument_id
        df['duration_seconds'] = duration_seconds
        return df

class Binance(ExchangeAdapter): name = 'binance'
class Bybit(ExchangeAdapter): name = 'bybit'
class OKX(ExchangeAdapter): name = 'okx'

ADAPTERS = {x.name:x() for x in (Binance,Bybit,OKX,ExchangeAdapter)}
