"""Five proposed external-factor signals; no data loading, fitting or execution.

All output values are native-perpetual signed directions at completed bar ends.
External inputs are joined only after their declared publication availability.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

FAMILIES = {
    'qqq_risk_transmission': 'Next-UTC-day QQQ risk-appetite transmission',
    'cpi_acceleration_event': 'First-release CPI acceleration event drift, not surprise',
    'funding_crowding_fade': 'Past-settled perpetual funding crowding fade',
    'perpetual_premium_fade': 'Trade/spot premium convergence directional proxy',
    'taker_flow_drift': 'Lagged aggregate aggressive trade-flow continuation',
}
SCALES = (.8, 1., 1.2)


def _rounded(value):
    return max(1, int(math.floor(value + .5)))


def parameters(family, scale=1.):
    if family not in FAMILIES or float(scale) not in SCALES:
        raise ValueError('Unknown family or undeclared scale')
    s = float(scale)
    if family == 'qqq_risk_transmission':
        return dict(short_sessions=_rounded(5*s), long_sessions=_rounded(20*s), threshold=.01,
                    stale_hours=96, daily_decision='00:01 UTC')
    if family == 'cpi_acceleration_event':
        return dict(acceleration_percentage_points=.1, hold_minutes=_rounded(1440*s),
                    availability_lag_minutes=1, consensus_used=False)
    if family == 'funding_crowding_fade':
        return dict(last_settlements=3, entry_rate=.0003, exit_rate=.00015,
                    stale_hours=12, maximum_hold_minutes=_rounded(1440*s), cooldown_minutes=60)
    if family == 'taker_flow_drift':
        return dict(window_minutes=_rounded(60*s), entry_imbalance=.05, exit_imbalance=.02,
                    maximum_hold_minutes=_rounded(360*s), cooldown_minutes=60, publication_lag_minutes=1)
    return dict(window_minutes=_rounded(60*s), entry_log_premium=math.log1p(.003),
                exit_log_premium=math.log1p(.001), maximum_hold_minutes=_rounded(720*s),
                cooldown_minutes=60, publication_lag_minutes=1)


def _clock(values, name):
    out = pd.DatetimeIndex(values)
    if out.tz is None:
        raise ValueError(f'{name} must be timezone aware')
    if out.hasnans:
        raise ValueError(f'{name} contains missing times')
    return out.tz_convert('UTC').as_unit('ns')


def _bars(frame):
    required = {'timestamp','close','duration_seconds','instrument_id'}
    if not required <= set(frame):
        raise ValueError('Missing minute bar columns')
    if frame.empty:
        raise ValueError('Target bars cannot be empty')
    out = frame.copy()
    out['timestamp'] = _clock(out.timestamp, 'bar timestamp')
    out = out.sort_values('timestamp').reset_index(drop=True)
    if out.timestamp.duplicated().any() or out.instrument_id.nunique()!=1:
        raise ValueError('Bars require one identity and unique timestamps')
    if not out.duration_seconds.eq(60).all():
        raise ValueError('Only one-minute observations supported')
    if not str(out.instrument_id.iloc[0]).startswith('binance:perpetual:'):
        raise ValueError('Target must be native perpetual')
    close = pd.to_numeric(out.close,errors='raise')
    if ((~np.isfinite(close)) | close.le(0)).any():
        raise ValueError('Target close must be finite and positive')
    out['close'] = close
    out['end'] = out.timestamp + pd.Timedelta(minutes=1)
    return out


def _asof(clock, table, cols):
    if table.empty:
        return pd.DataFrame(index=clock, columns=cols, dtype=float)
    left = pd.DataFrame({'decision_time':clock})
    joined = pd.merge_asof(left,table.sort_values('available_at'),left_on='decision_time',
                           right_on='available_at',direction='backward',allow_exact_matches=True)
    joined.index = clock
    return joined


def _qqq_feature(clock, observations, p):
    if observations is None:
        raise ValueError('QQQ observations required')
    x = observations.copy()
    if not {'available_at','session_date','close'} <= set(x):
        raise ValueError('QQQ availability/session/close columns required')
    if x.empty:
        result = pd.Series(0,index=clock,dtype=np.int8)
        result.attrs['fresh'] = pd.Series(False,index=clock)
        return result
    x['available_at'] = _clock(x.available_at,'QQQ availability')
    x = x.sort_values('available_at').reset_index(drop=True)
    if x.available_at.duplicated().any() or x.session_date.duplicated().any():
        raise ValueError('Duplicate QQQ session/availability')
    sessions = pd.to_datetime(x.session_date,utc=True)
    if not x.available_at.eq(sessions+pd.Timedelta(days=1)).all():
        raise ValueError('QQQ requires next UTC day availability')
    if 'price_basis' in x and not x.price_basis.astype(str).str.lower().str.contains('unadjusted').all():
        raise ValueError('QQQ must be unadjusted')
    valid = np.isfinite(x.close) & x.close.gt(0)
    # Missing/invalid observations reset session windows, rather than compressing them.
    segment = (~valid).cumsum()
    logs = np.log(x.close.where(valid))
    short = logs.groupby(segment).diff(p['short_sessions'])
    long = logs.groupby(segment).diff(p['long_sessions'])
    x['direction'] = np.select([(short>math.log1p(.01)) & (long>0),
                                (short<-math.log1p(.01)) & (long<0)],[1,-1],default=0)
    j = _asof(clock,x[['available_at','direction']],['direction'])
    stale = pd.Series(clock,index=clock)-j.available_at > pd.Timedelta(hours=96)
    result = j.direction.fillna(0).where(~stale,0).astype(np.int8)
    result.attrs['fresh'] = j.available_at.notna() & ~stale
    return result


def _cpi_feature(clock, events, p):
    if events is None:
        raise ValueError('CPI first-release events required')
    x = events.copy()
    required = {'available_at','release_time','reference_month','headline_yoy','core_yoy'}
    if not required <= set(x):
        raise ValueError('CPI first-release columns required')
    if x.empty:
        return pd.Series(0,index=clock,dtype=np.int8)
    x['available_at'] = _clock(x.available_at,'CPI availability')
    x['release_time'] = _clock(x.release_time,'CPI actual release')
    x = x.sort_values('available_at').reset_index(drop=True)
    if x.available_at.duplicated().any() or x.reference_month.duplicated().any():
        raise ValueError('Duplicate CPI first-release event')
    if not x.available_at.eq(x.release_time+pd.Timedelta(minutes=1)).all():
        raise ValueError('CPI must have one-minute publication lag')
    months = pd.PeriodIndex(x.reference_month,freq='M').asi8
    consecutive = np.r_[False,np.diff(months)==1]
    h = pd.to_numeric(x.headline_yoy,errors='raise'); c = pd.to_numeric(x.core_yoy,errors='raise')
    if ((~np.isfinite(h)) | (~np.isfinite(c))).any():
        raise ValueError('First-release CPI headline/core must be finite')
    dh,dc = h.diff(),c.diff()
    tol = 1e-12
    x['direction'] = np.select([consecutive & (dh>=.1-tol) & (dc>=.1-tol),
                               consecutive & (dh<=-.1+tol) & (dc<=-.1+tol)],[-1,1],default=0)
    x['deadline'] = x.available_at + pd.to_timedelta(p['hold_minutes'],unit='m')
    j = _asof(clock,x[['available_at','direction','deadline']],['direction'])
    active = pd.Series(clock,index=clock)<j.deadline
    return j.direction.fillna(0).where(active,0).astype(np.int8)


def _funding_feature(clock, events):
    if events is None or not {'timestamp','funding_rate'} <= set(events):
        raise ValueError('Actual settlement timestamps/rates required')
    x = events.copy()
    if x.empty:
        return pd.Series(np.nan,index=clock)
    x['timestamp'] = _clock(x.timestamp,'funding settlement')
    x = x.sort_values('timestamp').reset_index(drop=True)
    if x.timestamp.duplicated().any():
        raise ValueError('Duplicate funding settlement')
    if 'instrument_id' in x and x.instrument_id.nunique()>1:
        raise ValueError('One native funding identity required')
    rates = pd.to_numeric(x.funding_rate,errors='raise')
    rates = rates.where(np.isfinite(rates))
    x['rate'] = rates
    if 'available_at' in x:
        receipt = _clock(x.available_at,'funding actual receipt')
        if (receipt < pd.DatetimeIndex(x.timestamp)).any():
            raise ValueError('Funding receipt cannot precede settlement')
        x['available_at'] = receipt + pd.Timedelta(minutes=1)
    else:
        x['available_at'] = x.timestamp + pd.Timedelta(minutes=1)
    # A late-delivered earlier settlement cannot enter a rolling feature before receipt.
    published = {}
    records = []
    for event in x.sort_values(['available_at','timestamp']).itertuples():
        published[event.timestamp] = event.rate
        latest = sorted(published)[-3:]
        recent = [published[stamp] for stamp in latest]
        value = float(np.mean(recent)) if len(recent)==3 and np.isfinite(recent).all() else np.nan
        records.append({'available_at':event.available_at,'timestamp':latest[-1],'value':value})
    table = pd.DataFrame(records).drop_duplicates('available_at',keep='last')
    j = _asof(clock,table,['value'])
    fresh = pd.Series(clock,index=clock)-j.timestamp <= pd.Timedelta(hours=12)
    return j.value.where(fresh)


def _premium_feature(bars, spot_bars, units, p):
    if spot_bars is None or units<=0 or not np.isfinite(units):
        raise ValueError('Matched-unit spot observations required')
    x = spot_bars.copy()
    if not {'timestamp','close','duration_seconds','instrument_id'} <= set(x):
        raise ValueError('Spot bar columns required')
    x['timestamp'] = _clock(x.timestamp,'spot timestamp')
    if x.timestamp.duplicated().any() or x.instrument_id.nunique()!=1 or not x.duration_seconds.eq(60).all():
        raise ValueError('Unique single spot identity and minute grid required')
    if not str(x.instrument_id.iloc[0]).startswith('binance:spot:'):
        raise ValueError('Executable spot trade bars required')
    joined = bars[['timestamp','close','end']].merge(x[['timestamp','close']],on='timestamp',how='left',suffixes=('_perp','_spot'),validate='one_to_one')
    valid = np.isfinite(joined.close_perp)&np.isfinite(joined.close_spot)&joined.close_perp.gt(0)&joined.close_spot.gt(0)
    contiguous = joined.timestamp.diff().eq(pd.Timedelta(minutes=1))
    segment = ((~valid)|(~contiguous)).cumsum()
    premium = np.log((joined.close_perp/units)/joined.close_spot).where(valid)
    med = premium.groupby(segment).rolling(p['window_minutes'],min_periods=p['window_minutes']).median().reset_index(level=0,drop=True).sort_index()
    table = pd.DataFrame({'available_at':joined.end+pd.Timedelta(minutes=1),'value':med})
    j = _asof(pd.DatetimeIndex(bars.end),table,['value'])
    return j.value.where(j.available_at.eq(pd.Series(pd.DatetimeIndex(bars.end),index=pd.DatetimeIndex(bars.end))))


def _flow_feature(clock, observations, iid, p):
    if observations is None:
        raise ValueError('Official aggregate native trade-flow observations required')
    x = observations.copy()
    required = {'timestamp','available_at','instrument_id','total_volume','taker_buy_volume'}
    if not required <= set(x):
        raise ValueError('Missing flow columns')
    if x.empty:
        return pd.Series(np.nan,index=clock)
    x['timestamp'] = _clock(x.timestamp,'flow minute start')
    x['available_at'] = _clock(x.available_at,'flow publication')
    x = x.sort_values('timestamp').reset_index(drop=True)
    if x.timestamp.duplicated().any() or not x.instrument_id.eq(iid).all():
        raise ValueError('Duplicate or wrong native flow identity')
    if not x.available_at.eq(x.timestamp+pd.Timedelta(minutes=2)).all():
        raise ValueError('Flow requires completed minute plus one publication minute')
    total = pd.to_numeric(x.total_volume,errors='raise')
    buys = pd.to_numeric(x.taker_buy_volume,errors='raise')
    if ((~np.isfinite(total))|(~np.isfinite(buys))|(total<0)|(buys<0)|(buys>total+1e-9)).any():
        raise ValueError('Invalid aggregate trade volume')
    segment = (~x.timestamp.diff().eq(pd.Timedelta(minutes=1))).cumsum()
    n = p['window_minutes']
    denom = total.groupby(segment).rolling(n,min_periods=n).sum().reset_index(level=0,drop=True).sort_index()
    numerator = (2*buys-total).groupby(segment).rolling(n,min_periods=n).sum().reset_index(level=0,drop=True).sort_index()
    x['value'] = (numerator/denom).where(denom>0)
    j = _asof(clock,x[['available_at','value']],['value'])
    return j.value.where(j.available_at.eq(pd.Series(clock,index=clock)))


def build_signals(bars, family, scale=1., *, qqq=None, cpi=None, funding=None,
                  spot_bars=None, spot_units_per_perpetual_unit=1., flow=None):
    p = parameters(family,scale)
    b = _bars(bars)
    clock = pd.DatetimeIndex(b.end)
    if family=='qqq_risk_transmission':
        values = _qqq_feature(clock,qqq,p)
    elif family=='cpi_acceleration_event':
        values = _cpi_feature(clock,cpi,p)
    elif family=='funding_crowding_fade':
        if funding is not None and 'instrument_id' in funding and not funding.instrument_id.eq(b.instrument_id.iloc[0]).all():
            raise ValueError('Native funding and target identities differ')
        values = _funding_feature(clock,funding)
    elif family=='taker_flow_drift':
        values = _flow_feature(clock,flow,b.instrument_id.iloc[0],p)
    else:
        target = str(b.instrument_id.iloc[0]).split(':')[-1]
        spot = None if spot_bars is None or spot_bars.empty else str(spot_bars.instrument_id.iloc[0]).split(':')[-1]
        expected = 'PEPEUSDT' if target=='1000PEPEUSDT' else target
        expected_units = 1000. if target=='1000PEPEUSDT' else 1.
        if spot!=expected or float(spot_units_per_perpetual_unit)!=expected_units:
            raise ValueError('Native contract/spot unit mapping mismatch')
        values = _premium_feature(b,spot_bars,float(spot_units_per_perpetual_unit),p)
    output = np.zeros(len(b),dtype=np.int8)
    direction=0; entered=None; cooldown_until=None
    previous=None
    for k,(t,value) in enumerate(zip(clock,values)):
        gap = previous is not None and t-previous!=pd.Timedelta(minutes=1)
        if gap:
            direction=0;entered=None;cooldown_until=t+pd.Timedelta(hours=1)
        previous=t
        if family=='qqq_risk_transmission':
            # Missing or stale QQQ data can flatten immediately; otherwise daily reviews only.
            if t.hour==0 and t.minute==1:
                direction=int(value)
            elif not bool(values.attrs['fresh'].iloc[k]):
                direction=0
        elif family=='cpi_acceleration_event':
            direction=int(value)
        else:
            review=t.minute==1
            finite=pd.notna(value) and np.isfinite(value)
            exit_threshold=p.get('exit_rate',p.get('exit_log_premium',p.get('exit_imbalance')))
            expired=entered is not None and t-entered>=pd.Timedelta(minutes=p['maximum_hold_minutes'])
            reversal=finite and direction!=0 and (np.sign(value)!=direction if family=='taker_flow_drift' else np.sign(value)==direction)
            if direction and (expired or not finite or (review and (abs(value)<exit_threshold or reversal))):
                direction=0;entered=None;cooldown_until=t+pd.Timedelta(hours=1)
            entry_threshold=p.get('entry_rate',p.get('entry_log_premium',p.get('entry_imbalance')))
            if not direction and review and finite and abs(value)>=entry_threshold and (cooldown_until is None or t>=cooldown_until):
                direction=int(np.sign(value))*(1 if family=='taker_flow_drift' else -1);entered=t
        output[k]=direction
    return pd.Series(output,index=clock,name=family,dtype=np.int8)
