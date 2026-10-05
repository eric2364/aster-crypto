"""Five preregistered, causal long/cash minute-data signal families.

These are hypotheses, not successful strategies. This builder never inspects
realized strategy returns or selects parameters. Each signal is known only at its candle's end; execute
through the audited event engine at eligible subsequent observations. Signals
represent held direction, never a request for per-minute position resizing.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

FAMILIES = {
    'trend': {'description':'Slow trend with 6h/24h averages and hysteresis',
              'parameters':{'fast_minutes':360,'slow_minutes':1440,'entry_buffer':.003,'exit_buffer':.001,'entry_interval_minutes':60}},
    'donchian': {'description':'Previous 24h high breakout, previous 6h low exit',
                 'parameters':{'entry_minutes':1440,'exit_minutes':360,'atr_minutes':240,'atr_buffer':.25,'entry_interval_minutes':15,'cooldown_minutes':60}},
    'mean_reversion': {'description':'6h downside deviation plus 4h RSI, bounded hold',
                       'parameters':{'lookback_minutes':360,'rsi_minutes':240,'entry_z':-2.,'entry_rsi':30.,'exit_z':-.25,'exit_rsi':50.,'max_hold_minutes':720,'entry_interval_minutes':30,'cooldown_minutes':120}},
    'volatility_breakout': {'description':'Low-width 6h volatility channel breakout',
                           'parameters':{'channel_minutes':360,'width_history_minutes':10080,'width_quantile':.35,'channel_deviations':2.,'max_hold_minutes':1440,'entry_interval_minutes':15,'cooldown_minutes':120}},
    'trend_pullback': {'description':'Buy 4h RSI pullback while above 24h trend',
                       'parameters':{'trend_minutes':1440,'rsi_minutes':240,'entry_rsi':40.,'exit_rsi':65.,'max_hold_minutes':1440,'entry_interval_minutes':30,'cooldown_minutes':120}}
}


def parameters(family: str, scale: float = 1.0) -> dict:
    """Scale duration lookbacks/holds; thresholds and decision schedule stay fixed."""
    if family not in FAMILIES:
        raise ValueError(f'Unknown family {family}; choose {list(FAMILIES)}')
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError('scale must be finite and positive')
    out = FAMILIES[family]['parameters'].copy()
    for key,value in out.items():
        if key.endswith('_minutes') and key != 'entry_interval_minutes':
            out[key] = max(2,int(round(value*scale)))
    return out


def _rsi(close: pd.Series, lookback: int) -> pd.Series:
    # RSI is measured on completed 15-minute observations, not hundreds of
    # near-zero minute deltas that mechanically compress RSI toward 50.
    sampled=close.resample('15min',label='right',closed='right').last()
    periods=max(2,int(np.ceil(lookback/15)))
    delta=sampled.diff()
    up=delta.clip(lower=0).rolling(periods,min_periods=periods).mean()
    down=(-delta.clip(upper=0)).rolling(periods,min_periods=periods).mean()
    rsi=100-100/(1+up/down.replace(0,np.nan))
    rsi=rsi.mask((down==0)&(up>0),100).mask((down==0)&(up==0),50)
    return rsi.reindex(close.index,method='ffill')


def _state(index, entry, exit, interval, cooldown=0, max_hold=None):
    """Fixed entry/exit state. Gaps break holding eligibility; cooldown uses UTC."""
    entry=np.asarray(entry.fillna(False),dtype=bool)
    exit=np.asarray(exit.fillna(False),dtype=bool)
    values=np.zeros(len(index),dtype=np.int8)
    held=False;entered=0;next_entry=0
    clock=index.as_unit('ns').asi8
    minute_ns=60_000_000_000
    scheduled=(clock//minute_ns)%interval==0
    cooldown_ns=cooldown*minute_ns
    max_hold_ns=max_hold*minute_ns if max_hold is not None else None
    for i,now in enumerate(clock):
        gap=i>0 and now-clock[i-1] != minute_ns
        timed_out=held and max_hold_ns is not None and now-entered >= max_hold_ns
        if held and (exit[i] or timed_out or gap):
            held=False;next_entry=now+cooldown_ns
        # Never exit then reenter on one observation. Gaps disallow entries too.
        elif not held and not gap and entry[i] and scheduled[i] and now>=next_entry:
            held=True;entered=now
        values[i]=int(held)
    return pd.Series(values,index=index,name='signal')


def build_signals(bars: pd.DataFrame, family: str, scale: float = 1.0) -> pd.Series:
    """Return one instrument's long/cash intent at minute-candle availability.

    Input must be a single instrument with timezone-aware interval-start time,
    one-minute duration and positive finite OHLC. Input order may be unsorted;
    duplicates are rejected. Rolling windows never center or use negative shifts.
    History spanning a gap must warm up again: each continuous block is independent.
    """
    p=parameters(family,scale)
    required={'timestamp','open','high','low','close','duration_seconds'}
    if not required<=set(bars):raise ValueError(f'Missing fields: {sorted(required-set(bars))}')
    if 'instrument_id' in bars and bars.instrument_id.nunique()!=1:
        raise ValueError('build_signals requires one instrument at a time')
    if bars.empty:return pd.Series(dtype=np.int8,index=pd.DatetimeIndex([],tz='UTC'),name='signal')
    frame=bars.copy()
    stamps=pd.to_datetime(frame.timestamp,format='mixed')
    if not isinstance(stamps.dtype,pd.DatetimeTZDtype):raise ValueError('Timezone-aware start timestamps required')
    if stamps.isna().any():raise ValueError('Missing timestamps are not allowed')
    frame['end']=stamps.dt.tz_convert('UTC')+pd.to_timedelta(frame.duration_seconds,unit='s')
    frame=frame.sort_values('end').reset_index(drop=True)
    if frame.end.duplicated().any() or not frame.duration_seconds.eq(60).all():raise ValueError('Unique one-minute bars required')
    array=frame[['open','high','low','close']].to_numpy(dtype=float)
    if not np.isfinite(array).all() or (array<=0).any():raise ValueError('Finite positive OHLC required')
    if not ((frame.high >= frame[['open','close','low']].max(axis=1)) &
            (frame.low <= frame[['open','close','high']].min(axis=1))).all():raise ValueError('Invalid OHLC')
    # Recursive continuous-block evaluation prevents a rolling window from spanning outages.
    blocks=frame.end.diff().ne(pd.Timedelta(minutes=1)).cumsum()
    if blocks.nunique()>1:
        return pd.concat([build_signals(g.drop(columns='end'),family,scale) for _,g in frame.groupby(blocks,sort=True)])
    index=pd.DatetimeIndex(frame.end,name='available_at')
    close=pd.Series(frame.close.to_numpy(dtype=float),index=index)
    high=pd.Series(frame.high.to_numpy(dtype=float),index=index)
    low=pd.Series(frame.low.to_numpy(dtype=float),index=index)
    interval=p['entry_interval_minutes']
    if family=='trend':
        fast=close.rolling(p['fast_minutes'],min_periods=p['fast_minutes']).mean()
        slow=close.rolling(p['slow_minutes'],min_periods=p['slow_minutes']).mean()
        entry=(fast>slow*(1+p['entry_buffer'])) & (close>slow)
        exit=(fast<slow*(1-p['exit_buffer'])) | (close<slow*(1-p['entry_buffer']))
        return _state(index,entry,exit,interval)
    if family=='donchian':
        upper=high.shift(1).rolling(p['entry_minutes'],min_periods=p['entry_minutes']).max()
        lower=low.shift(1).rolling(p['exit_minutes'],min_periods=p['exit_minutes']).min()
        true_range=pd.concat([high-low,(high-close.shift(1)).abs(),(low-close.shift(1)).abs()],axis=1).max(axis=1)
        atr=true_range.shift(1).rolling(p['atr_minutes'],min_periods=p['atr_minutes']).mean()
        entry=close>upper+p['atr_buffer']*atr
        return _state(index,entry,close<lower,interval,p['cooldown_minutes'])
    if family=='mean_reversion':
        mean=close.shift(1).rolling(p['lookback_minutes'],min_periods=p['lookback_minutes']).mean()
        std=close.shift(1).rolling(p['lookback_minutes'],min_periods=p['lookback_minutes']).std(ddof=1)
        z=(close-mean)/std.replace(0,np.nan)
        rsi=_rsi(close,p['rsi_minutes'])
        entry=(z<p['entry_z']) & (rsi<p['entry_rsi'])
        exit=(z>p['exit_z']) | (rsi>p['exit_rsi'])
        return _state(index,entry,exit,interval,p['cooldown_minutes'],p['max_hold_minutes'])
    if family=='volatility_breakout':
        mean=close.shift(1).rolling(p['channel_minutes'],min_periods=p['channel_minutes']).mean()
        std=close.shift(1).rolling(p['channel_minutes'],min_periods=p['channel_minutes']).std(ddof=1)
        width=std/mean
        # Threshold excludes current width, and can never inspect later volatility.
        threshold=width.shift(1).rolling(p['width_history_minutes'],min_periods=p['width_history_minutes']).quantile(p['width_quantile'])
        entry=(width<threshold) & (close>mean+p['channel_deviations']*std)
        exit=close<mean
        return _state(index,entry,exit,interval,p['cooldown_minutes'],p['max_hold_minutes'])
    if family=='trend_pullback':
        trend=close.rolling(p['trend_minutes'],min_periods=p['trend_minutes']).mean()
        rsi=_rsi(close,p['rsi_minutes'])
        entry=(close>trend) & (rsi<p['entry_rsi'])
        exit=(close<trend) | (rsi>p['exit_rsi'])
        return _state(index,entry,exit,interval,p['cooldown_minutes'],p['max_hold_minutes'])
    raise AssertionError('Unhandled registered family')



def bootstrap_daily_returns(returns, seed: int = 42, samples: int = 10000,
                            block_days: int = 7) -> dict:
    """Descriptive circular moving-block intervals for mean daily holdout return.

    Block length and seed must be fixed before looking at holdout. The 99% interval
    is the two-sided .05/5 Bonferroni interval for five preregistered families.
    These percentile intervals do not establish repeatable future profitability.
    """
    values=np.asarray(returns,dtype=float)
    if values.ndim!=1 or not np.isfinite(values).all():
        raise ValueError('Supply finite one-dimensional daily returns')
    if block_days<1 or samples<1:raise ValueError('Positive block length and sample count required')
    n=len(values)
    out={'daily_observations':n,'block_days':block_days,'bootstrap_samples':samples,
         'seed':seed,'mean_daily_return':float(values.mean()) if n else None,
         'mean_daily_ci95':None,'mean_daily_ci99_bonferroni5':None}
    if n<2*block_days:return out
    rng=np.random.default_rng(seed)
    blocks=int(np.ceil(n/block_days))
    starts=rng.integers(0,n,size=(samples,blocks))
    positions=(starts[:,:,None]+np.arange(block_days))%n
    draws=values[positions.reshape(samples,-1)[:,:n]].mean(axis=1)
    out['mean_daily_ci95']=np.quantile(draws,[.025,.975]).tolist()
    out['mean_daily_ci99_bonferroni5']=np.quantile(draws,[.005,.995]).tolist()
    return out
