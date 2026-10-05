"""Future replay contracts; not executable matching modes."""
from dataclasses import dataclass
import pandas as pd

@dataclass(frozen=True)
class Quote:
    timestamp: pd.Timestamp
    instrument_id: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float

@dataclass(frozen=True)
class BookSnapshot:
    timestamp: pd.Timestamp
    instrument_id: str
    bids: tuple[tuple[float,float], ...]
    asks: tuple[tuple[float,float], ...]
    sequence: int

@dataclass(frozen=True)
class TradeTick:
    timestamp: pd.Timestamp
    instrument_id: str
    price: float
    quantity: float
    aggressor_side: int
