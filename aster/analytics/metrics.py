"""Timestamp-aware crypto analytics; no costs are applied to equity a second time."""
from __future__ import annotations

import math
from typing import Any
import numpy as np
import pandas as pd

SECONDS_PER_YEAR = 365 * 24 * 3600


def json_safe(value: Any) -> Any:
    """Recursively convert NumPy scalars and nonfinite values for strict JSON."""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def equity_series(frame: pd.DataFrame) -> pd.Series:
    if not {'timestamp', 'equity'} <= set(frame):
        raise ValueError('equity requires timestamp and equity columns')
    index = pd.DatetimeIndex(pd.to_datetime(frame.timestamp, utc=True))
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError('equity timestamps must be unique and chronological')
    values = pd.to_numeric(frame.equity, errors='raise').to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError('equity values must be finite')
    return pd.Series(values, index=index, name='equity')


def daily_returns(frame: pd.DataFrame) -> pd.Series:
    """UTC daily closing returns, first observed day measured from initial equity.

    Empty calendar days are held at the last observed equity. This assumes the
    supplied equity ledger is complete; it does not repair missing market data.
    """
    series = equity_series(frame)
    if series.empty:
        return pd.Series(dtype=float, name='return')
    closes = series.resample('1D').last().ffill()
    previous = closes.shift(1)
    previous.iloc[0] = series.iloc[0]
    result = closes / previous - 1
    # A zero/negative equity account does not have meaningful compounded returns.
    result[(previous <= 0) | (closes < 0)] = np.nan
    # A baseline-only first day contributes no sampled return.
    if len(series) == 1 or (series.index[1:].normalize() != series.index[0].normalize()).all():
        result = result.iloc[1:]
    return result.rename('return')


def drawdown_stats(frame: pd.DataFrame) -> dict:
    series = equity_series(frame)
    if series.empty:
        return {'max_drawdown': None, 'max_drawdown_duration_days': None,
                'max_recovery_days': None, 'currently_underwater': False}
    peak = series.cummax()
    drawdown = series / peak - 1
    drawdown[peak <= 0] = np.nan
    longest, recoveries = 0.0, []
    peak_time = series.index[0]
    trough_time, trough_value, active = peak_time, 0.0, False
    for timestamp, value in drawdown.items():
        if pd.isna(value):
            continue
        if value >= -1e-14:
            if active:
                longest = max(longest, (timestamp - peak_time).total_seconds() / 86400)
                recoveries.append((timestamp - trough_time).total_seconds() / 86400)
            peak_time, active, trough_value = timestamp, False, 0.0
        else:
            active = True
            if value < trough_value:
                trough_time, trough_value = timestamp, value
            longest = max(longest, (timestamp - peak_time).total_seconds() / 86400)
    return {'max_drawdown': float(-drawdown.min()),
            'max_drawdown_duration_days': longest,
            'max_recovery_days': max(recoveries) if recoveries else None,
            'currently_underwater': active}


def monthly_returns(frame: pd.DataFrame) -> pd.DataFrame:
    series = equity_series(frame)
    if series.empty:
        return pd.DataFrame(columns=['year', 'month', 'return'])
    closes = series.resample('ME').last().ffill()
    previous = closes.shift(1)
    previous.iloc[0] = series.iloc[0]
    returns = closes / previous - 1
    returns[(previous <= 0) | (closes < 0)] = np.nan
    return pd.DataFrame({'year': closes.index.year, 'month': closes.index.month,
                         'return': returns.to_numpy()})


def rolling_statistics(frame: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    if window < 2:
        raise ValueError('rolling window must be at least two days')
    returns = daily_returns(frame)
    roll = returns.rolling(window, min_periods=window)
    vol = roll.std(ddof=1)
    out = pd.DataFrame({'timestamp': returns.index, 'rolling_sharpe':
                        (roll.mean() / vol * np.sqrt(365)).to_numpy(),
                        'rolling_volatility': (vol * np.sqrt(365)).to_numpy(),
                        'rolling_return': roll.apply(lambda x: np.prod(1+x)-1, raw=True).to_numpy()})
    closes = equity_series(frame).resample('1D').last().ffill().reindex(returns.index)
    out['rolling_drawdown'] = closes.rolling(window).apply(
        lambda x: np.max(1 - x / np.maximum.accumulate(x)) if np.all(x > 0) else np.nan,
        raw=True).to_numpy()
    return out.replace([np.inf, -np.inf], np.nan)


def regime_analysis(frame: pd.DataFrame, benchmark: pd.DataFrame | None = None,
                    window: int = 30) -> pd.DataFrame:
    """Causal descriptive regimes using lagged benchmark (or portfolio) returns."""
    returns = daily_returns(frame)
    base = daily_returns(benchmark) if benchmark is not None else returns
    past = base.shift(1).rolling(window, min_periods=window)
    trend = past.apply(lambda x: np.prod(1+x)-1, raw=True)
    vol = past.std(ddof=1) * np.sqrt(365)
    labels = pd.Series('unknown', index=base.index)
    labels[trend > .05] = 'bull'
    labels[trend < -.05] = 'bear'
    labels[trend.abs() <= .05] = 'sideways'
    volatility = pd.Series('unknown', index=base.index)
    volatility[vol >= .60] = 'high_volatility'
    volatility[vol < .60] = 'low_volatility'
    return pd.DataFrame({'timestamp': returns.index, 'return': returns.to_numpy(),
                         'regime': labels.reindex(returns.index).fillna('unknown').to_numpy(),
                         'volatility_regime': volatility.reindex(returns.index).fillna('unknown').to_numpy()})


def _ratio(a: float, b: float) -> float | None:
    return a / b if b > 0 else None


def _last(frame: pd.DataFrame, name: str) -> float:
    return float(frame[name].iloc[-1]) if name in frame and len(frame) else 0.0


def _weighted(frame: pd.DataFrame, name: str, binary: bool = False) -> float | None:
    if name not in frame or len(frame) < 2:
        return None
    # Left-continuous holdings: a snapshot lasts until the following snapshot.
    times = pd.to_datetime(frame.timestamp, utc=True).astype('int64').to_numpy()
    weights = np.diff(times).astype(float)
    values = frame[name].to_numpy(dtype=float)[:-1]
    if binary:
        values = (values > 0).astype(float)
    return float(np.average(values, weights=weights)) if weights.sum() > 0 else None


def metrics(equity: pd.DataFrame, trades: pd.DataFrame | None = None,
            fills: pd.DataFrame | None = None, benchmark: pd.DataFrame | None = None) -> dict:
    """Metrics are fractions (not percentages); undefined quantities become null."""
    series = equity_series(equity)
    trades = pd.DataFrame() if trades is None else trades
    fills = pd.DataFrame() if fills is None else fills
    if series.empty:
        return {'total_return': None, 'trade_count': 0, 'initial_equity': None,
                'final_equity': None}
    initial, final = float(series.iloc[0]), float(series.iloc[-1])
    elapsed = (series.index[-1] - series.index[0]).total_seconds()
    returns = daily_returns(equity).dropna()
    std = float(returns.std(ddof=1)) if len(returns) > 1 else np.nan
    downside = float(np.sqrt(np.mean(np.minimum(returns.to_numpy(), 0)**2))) if len(returns) else np.nan
    cagr = None
    if initial > 0 and final > 0 and elapsed > 0:
        log_growth = math.log(final / initial) * SECONDS_PER_YEAR / elapsed
        cagr = math.expm1(log_growth) if log_growth < 709 else None
    out = {'initial_equity': initial, 'final_equity': final,
           'total_return': final / initial - 1 if initial > 0 else None,
           'cagr': cagr, 'annualized_volatility': std*np.sqrt(365),
           'sharpe': _ratio(float(returns.mean()) * np.sqrt(365), std),
           'sortino': _ratio(float(returns.mean()) * np.sqrt(365), downside),
           'elapsed_days': elapsed / 86400, 'daily_return_count': len(returns)}
    out.update(drawdown_stats(equity))
    out['calmar'] = _ratio(cagr, out['max_drawdown']) if cagr is not None else None
    out.update({'trading_pnl': _last(equity, 'realized_pnl') + _last(equity, 'unrealized_pnl'),
                'funding_pnl': _last(equity, 'funding_pnl'), 'trading_fees': _last(equity, 'trading_fees'),
                'slippage_cost': _last(equity, 'slippage_cost'), 'liquidation_fees': _last(equity, 'liquidation_fees'),
                'net_profit': final-initial,
                'liquidation_count': int(trades.exit_reason.eq('liquidation').sum()) if 'exit_reason' in trades else None,
                'average_turnover_per_day': _last(equity, 'turnover') / (elapsed / 86400) if elapsed > 0 else None,
                'turnover': _last(equity, 'turnover'),
                'turnover_multiple': _ratio(_last(equity, 'turnover'), initial)})
    for name in ['gross_exposure', 'net_exposure', 'long_exposure', 'short_exposure', 'gross_leverage']:
        out['average_' + name] = _weighted(equity, name)
        out['max_' + name] = float(equity[name].max()) if name in equity else None
    out['exposure_time'] = _weighted(equity, 'gross_exposure', binary=True)
    out['average_net_leverage'] = _weighted(equity.assign(net_leverage=equity.get('net_exposure', pd.Series(0, index=equity.index)) / equity.equity.replace(0, np.nan)), 'net_leverage')
    pnl = trades.net_pnl.to_numpy(dtype=float) if 'net_pnl' in trades else np.array([])
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    positive_profit = float(wins.sum())
    out.update({'trade_count': len(pnl), 'win_rate': len(wins)/len(pnl) if len(pnl) else None,
                'profit_factor': _ratio(positive_profit, float(-losses.sum())),
                'expectancy': float(pnl.mean()) if len(pnl) else None,
                'average_win': float(wins.mean()) if len(wins) else None,
                'average_loss': float(losses.mean()) if len(losses) else None,
                'payoff_ratio': _ratio(float(wins.mean()), float(-losses.mean())) if len(wins) and len(losses) else None,
                'gross_profit': positive_profit,
                'gross_loss': float(-losses.sum()),
                'trades_per_day': len(pnl)/(elapsed/86400) if elapsed > 0 else None,
                'pnl_per_trade': float(pnl.mean()) if len(pnl) else None,
                'pnl_per_unit_turnover': _ratio(final-initial, out['turnover']),
                'average_holding_seconds': float(trades.holding_seconds.mean()) if 'holding_seconds' in trades and len(trades) else None,
                'median_holding_seconds': float(trades.holding_seconds.median()) if 'holding_seconds' in trades and len(trades) else None})
    # Positive gross trade outcomes are the pre-fee denominator; gross_pnl already
    # embeds execution-price slippage, so never subtract slippage again.
    gross_positive = float(trades.gross_pnl.clip(lower=0).sum()) if 'gross_pnl' in trades else 0.0
    out['net_winning_trade_profit'] = out['gross_profit']
    out['net_losing_trade_loss'] = out['gross_loss']
    out['gross_profit'] = gross_positive if 'gross_pnl' in trades else None
    out['gross_loss'] = float(-trades.gross_pnl.clip(upper=0).sum()) if 'gross_pnl' in trades else None
    out['fees_as_fraction_gross_profit'] = _ratio(out['trading_fees'], gross_positive)
    out['slippage_as_fraction_gross_profit'] = _ratio(out['slippage_cost'], gross_positive)
    if len(fills) and {'quantity', 'price', 'liquidity_type'} <= set(fills):
        notionals = (fills.quantity * fills.price).abs()
        maker = fills.liquidity_type.eq('maker')
        taker = fills.liquidity_type.eq('taker')
        out.update({'fill_count': len(fills), 'maker_ratio': float(maker.mean()), 'taker_ratio': float(taker.mean()),
                    'maker_notional_ratio': _ratio(float(notionals[maker].sum()), float(notionals.sum())),
                    'maker_fees': float(fills.loc[maker, 'fee'].sum()) if 'fee' in fills else None,
                    'taker_fees': float(fills.loc[taker, 'fee'].sum()) if 'fee' in fills else None})
    else:
        out.update({'fill_count': 0, 'maker_ratio': None, 'taker_ratio': None,
                    'maker_notional_ratio': None, 'maker_fees': None, 'taker_fees': None})
    out['symbol_attribution'] = trades.groupby('symbol').net_pnl.sum().to_dict() if {'symbol', 'net_pnl'} <= set(trades) else {}
    out['exchange_attribution'] = trades.groupby('exchange').net_pnl.sum().to_dict() if {'exchange', 'net_pnl'} <= set(trades) else {}
    out['alpha'], out['beta'] = None, None
    if benchmark is not None:
        aligned = pd.concat([daily_returns(equity), daily_returns(benchmark)], axis=1, keys=['p', 'b']).dropna()
        variance = float(aligned.b.var(ddof=1)) if len(aligned) > 1 else 0
        if variance > 0:
            beta = float(aligned.p.cov(aligned.b)) / variance
            out['beta'] = beta
            out['alpha'] = float(aligned.p.mean() - beta*aligned.b.mean()) * 365
    return json_safe(out)
