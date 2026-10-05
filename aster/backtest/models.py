from dataclasses import dataclass, field
from enum import StrEnum
import math
import pandas as pd

class Market(StrEnum):
    SPOT = 'spot'
    PERPETUAL = 'perpetual'

class OrderType(StrEnum):
    MARKET = 'market'
    LIMIT = 'limit'
    STOP_MARKET = 'stop_market'
    STOP_LIMIT = 'stop_limit'

@dataclass(frozen=True)
class Instrument:
    id: str
    exchange: str
    symbol: str
    market_type: str = 'spot'
    base: str = 'BTC'
    quote: str = 'USDT'
    tick_size: float = 0.01
    lot_size: float = 0.001
    min_quantity: float = 0.001
    min_notional: float = 5.0
    maker_bps: float = 2.0
    taker_bps: float = 5.0
    max_leverage: float = 20.0
    maintenance_rate: float = 0.005
    liquidation_bps: float = 50.0
    funding_interval_hours: int = 8
    contract_type: str = 'linear'
    multiplier: float = 1.0
    listed_at: str | None = None
    delisted_at: str | None = None

    def __post_init__(self):
        if self.market_type not in ('spot', 'perpetual') or self.contract_type != 'linear' or self.multiplier != 1:
            raise ValueError('Only spot and linear base-unit perpetuals are implemented')
        values = [self.tick_size, self.lot_size, self.min_quantity, self.min_notional,
                  self.max_leverage, self.maintenance_rate, self.liquidation_bps,
                  self.maker_bps, self.taker_bps]
        if not all(math.isfinite(x) for x in values):
            raise ValueError('Instrument values must be finite')
        if min(self.tick_size, self.lot_size, self.min_quantity, self.max_leverage) <= 0 or self.min_notional < 0:
            raise ValueError('Invalid instrument increments or minimums')
        if not 0 <= self.maintenance_rate < 1 or self.liquidation_bps < 0:
            raise ValueError('Invalid margin policy')

@dataclass
class Order:
    instrument_id: str
    side: int
    quantity: float
    order_type: str = 'market'
    limit_price: float | None = None
    stop_price: float | None = None
    post_only: bool = False
    reduce_only: bool = False
    tif: str = 'GTC'
    id: str = ''
    submitted_at: pd.Timestamp | None = None
    active_at: pd.Timestamp | None = None
    remaining: float = 0
    status: str = 'new'
    first_seen: pd.Timestamp | None = None
    triggered: bool = False

@dataclass
class Position:
    quantity: float = 0
    average_price: float = 0
    collateral: float = 0
    entry_time: pd.Timestamp | None = None
    entry_quantity: float = 0
    maker_fees: float = 0
    taker_fees: float = 0
    funding: float = 0
    slippage: float = 0
    entry_order_type: str = ''

@dataclass
class SimulationConfig:
    initial_balances: dict[str, float] = field(default_factory=lambda: {'binance': 100000.0})
    leverage: float = 3.0
    margin_mode: str = 'isolated'
    max_gross_leverage: float = 3.0
    max_position_pct: float = 1.0
    fill_model: str = 'conservative'
    participation: float = 0.1
    slippage_bps: float = 2.0
    slippage_model: str = 'fixed'
    spread_bps: float = 2.0
    impact_bps: float = 10.0
    latency_ms: int = 0
    execution_delay_bars: int = 0
    seed: int = 42
    funding_enabled: bool = True
    record_every: int = 1

    def __post_init__(self):
        if self.margin_mode not in ('isolated', 'cross'):
            raise ValueError('Unsupported margin mode')
        if self.fill_model not in ('conservative', 'touch', 'volume_aware'):
            raise ValueError('L2 queue matching is not implemented')
        if self.slippage_model not in ('fixed', 'spread', 'volatility', 'volume'):
            raise ValueError('Unknown slippage model')
        vals = [self.leverage, self.max_gross_leverage, self.max_position_pct, self.participation,
                self.slippage_bps, self.spread_bps, self.impact_bps, *self.initial_balances.values()]
        if not all(math.isfinite(x) for x in vals) or not self.initial_balances:
            raise ValueError('Finite configuration and at least one wallet required')
        if min(self.leverage, self.max_gross_leverage, self.max_position_pct) <= 0 or not 0 < self.participation <= 1:
            raise ValueError('Invalid risk or capacity settings')
        if min(self.slippage_bps, self.spread_bps, self.impact_bps, *self.initial_balances.values()) < 0:
            raise ValueError('Negative execution inputs or cash')
        if min(self.latency_ms, self.execution_delay_bars) < 0 or self.record_every < 1:
            raise ValueError('Invalid timing settings')
