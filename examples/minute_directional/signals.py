"""Exploratory signed derivative hypotheses on a previously examined year.

The reused historical evaluation window is NOT an untouched holdout. Correlated
trend variants below are not five independent economic edges. This builder never
inspects strategy returns or selects parameters; no historical data is read here.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

FAMILIES={
 'slow_ema_trend':{'description':'3d/14d EMA trend with symmetric hysteresis',
  'parameters':{'fast_minutes':4320,'slow_minutes':20160,'entry_buffer':.003,'exit_buffer':.001,'decision_minutes':60,'cooldown_minutes':60}},
 'weekly_donchian':{'description':'Previous7d range breakout; previous3d exit channel',
  'parameters':{'entry_minutes':10080,'exit_minutes':4320,'decision_minutes':60,'cooldown_minutes':120}},
 'ts_momentum_agreement':{'description':'3d and7d return signs agree beyond1% threshold',
  'parameters':{'fast_minutes':4320,'slow_minutes':10080,'entry_threshold':.01,'decision_minutes':60,'cooldown_minutes':60}},
 'signed_mean_reversion':{'description':'24h two-deviation overshoot; return-to-mean exit',
  'parameters':{'lookback_minutes':1440,'entry_z':2.,'decision_minutes':15,'cooldown_minutes':180,'max_hold_minutes':2880,'close_stop_fraction':.12}},
 'btc_conditioned_alt_lag':{'description':'3h BTC move and3d trend; delayed altcoin response both directions',
  'parameters':{'return_minutes':180,'leader_trend_minutes':4320,'entry_return_threshold':.01,'catchup_threshold':.01,'decision_minutes':30,'cooldown_minutes':120,'max_hold_minutes':1440,'publication_lag_minutes':1,'leader_stale_minutes':2}}
}


def parameters(family,scale=1.0):
 if family not in FAMILIES:raise ValueError(f'Unknown directional family {family}')
 if not np.isfinite(scale) or scale<=0:raise ValueError('Positive finite scale required')
 p=FAMILIES[family]['parameters'].copy()
 for key,value in p.items():
  if key.endswith('_minutes') and key not in {'decision_minutes','publication_lag_minutes','leader_stale_minutes'}:
   p[key]=max(2,int(round(value*scale)))
 return p


def _frame(bars):
 needed={'timestamp','duration_seconds','open','high','low','close'}
 if not needed<=set(bars):raise ValueError(f'Missing {sorted(needed-set(bars))}')
 if bars.empty:return bars.copy()
 if 'instrument_id' in bars and bars.instrument_id.nunique()!=1:raise ValueError('Single instrument required')
 f=bars.copy();times=pd.to_datetime(f.timestamp,format='mixed')
 if not isinstance(times.dtype,pd.DatetimeTZDtype) or times.isna().any():raise ValueError('Nonmissing timezone-aware time required')
 if not f.duration_seconds.eq(60).all():raise ValueError('One-minute durations required')
 f['end']=(times.dt.tz_convert('UTC')+pd.Timedelta(minutes=1)).dt.as_unit('ns')
 f=f.sort_values('end').reset_index(drop=True)
 if f.end.duplicated().any():raise ValueError('Duplicate bars')
 prices=f[['open','high','low','close']].to_numpy(dtype=float)
 if not np.isfinite(prices).all() or (prices<=0).any():raise ValueError('Finite positive OHLC required')
 if not ((f.high>=f[['open','close','low']].max(axis=1))&(f.low<=f[['open','close','high']].min(axis=1))).all():raise ValueError('Impossible OHLC')
 return f


def _continuous(series,periods,operation):
 groups=series.index.to_series().diff().ne(pd.Timedelta(minutes=1)).cumsum().to_numpy()
 out=pd.Series(np.nan,index=series.index)
 for _,part in series.groupby(groups,sort=True):
  if operation=='return':value=part.pct_change(periods,fill_method=None)
  elif operation=='ema':value=part.ewm(span=periods,min_periods=periods,adjust=False).mean()
  elif operation=='mean':value=part.shift(1).rolling(periods,min_periods=periods).mean()
  elif operation=='std':value=part.shift(1).rolling(periods,min_periods=periods).std(ddof=1)
  elif operation=='max':value=part.shift(1).rolling(periods,min_periods=periods).max()
  elif operation=='min':value=part.shift(1).rolling(periods,min_periods=periods).min()
  else:raise ValueError('Unknown operation')
  out.loc[part.index]=value
 return out


def _held(index,close,long_entry,short_entry,long_exit,short_exit,p):
 arrays=[x.fillna(False).to_numpy(dtype=bool) for x in [long_entry,short_entry,long_exit,short_exit]]
 le,se,lx,sx=arrays;clock=index.as_unit('ns').asi8;minute=60_000_000_000
 prices=close.to_numpy(dtype=float);answer=np.zeros(len(index),dtype=np.int8)
 schedule=(clock//minute)%p['decision_minutes']==0
 held=0;entry_time=0;entry_price=0.;next_entry=0
 max_hold=p.get('max_hold_minutes',0)*minute;cooldown=p.get('cooldown_minutes',0)*minute
 stop=p.get('close_stop_fraction',None)
 for i,now in enumerate(clock):
  gap=i>0 and now-clock[i-1]!=minute
  time_exit=held and max_hold and now-entry_time>=max_hold
  stopped=held and stop is not None and held*(prices[i]/entry_price-1)<=-stop
  should_exit=(held==1 and lx[i]) or (held==-1 and sx[i])
  # Exit checks run on completed minute observations. Entry clock is coarser.
  if held and (should_exit or time_exit or stopped or gap):
   held=0;next_entry=now+cooldown
  elif not held and not gap and schedule[i] and now>=next_entry:
   if le[i] and not lx[i] and not se[i]:held=1
   elif se[i] and not sx[i] and not le[i]:held=-1
   if held:entry_time=now;entry_price=prices[i]
  answer[i]=held
 return pd.Series(answer,index=index,name='signal')


def build_signals(bars,family,scale=1.0,leader_bars=None):
 """Signed fixed-quantity intent at complete target-bar end; execution is separate.

 Cooldowns and max hold use clock time, not a count of missing observations.
 A12% close-stop is an observed-close signal, NOT an intrabar guaranteed fill.
 Quantity remains the runner's entered base units until this direction changes.
 """
 if family=='cross_sectional_momentum':raise ValueError('Use build_cross_signals for synchronized universe ranks')
 p=parameters(family,scale);f=_frame(bars)
 if f.empty:return pd.Series(dtype=np.int8,index=pd.DatetimeIndex([],tz='UTC'),name='signal')
 index=pd.DatetimeIndex(f.end,name='available_at')
 close=pd.Series(f.close.to_numpy(dtype=float),index=index)
 high=pd.Series(f.high.to_numpy(dtype=float),index=index);low=pd.Series(f.low.to_numpy(dtype=float),index=index)
 if family=='slow_ema_trend':
  fast=_continuous(close,p['fast_minutes'],'ema');slow=_continuous(close,p['slow_minutes'],'ema')
  le=(fast>slow*(1+p['entry_buffer']))&(close>slow)
  se=(fast<slow*(1-p['entry_buffer']))&(close<slow)
  lx=(fast<slow*(1-p['exit_buffer']))|(close<slow)
  sx=(fast>slow*(1+p['exit_buffer']))|(close>slow)
 elif family=='weekly_donchian':
  upper=_continuous(high,p['entry_minutes'],'max');lower=_continuous(low,p['entry_minutes'],'min')
  exit_low=_continuous(low,p['exit_minutes'],'min');exit_high=_continuous(high,p['exit_minutes'],'max')
  le=close>upper;se=close<lower;lx=close<exit_low;sx=close>exit_high
 elif family=='ts_momentum_agreement':
  fast=_continuous(close,p['fast_minutes'],'return');slow=_continuous(close,p['slow_minutes'],'return')
  le=(fast>p['entry_threshold'])&(slow>p['entry_threshold'])
  se=(fast<-p['entry_threshold'])&(slow<-p['entry_threshold'])
  lx=(fast<=0)|(slow<=0);sx=(fast>=0)|(slow>=0)
 elif family=='signed_mean_reversion':
  mean=_continuous(close,p['lookback_minutes'],'mean');std=_continuous(close,p['lookback_minutes'],'std')
  z=(close-mean)/std.replace(0,np.nan)
  le=z<-p['entry_z'];se=z>p['entry_z'];lx=close>=mean;sx=close<=mean
 else:
  symbols=f.instrument_id.astype(str).str.split(':').str[-1] if 'instrument_id' in f else f.get('symbol',pd.Series(dtype=str))
  if len(symbols) and symbols.eq('BTCUSDT').all():return pd.Series(0,index=index,dtype=np.int8,name='signal')
  if leader_bars is None:raise ValueError('Completed BTC bars required')
  leader=_frame(leader_bars)
  identities=leader.instrument_id.astype(str).str.split(':').str[-1] if 'instrument_id' in leader else leader.get('symbol',pd.Series(dtype=str))
  if not len(identities) or not identities.eq('BTCUSDT').all():raise ValueError('BTCUSDT leader required')
  li=pd.DatetimeIndex(leader.end);lp=pd.Series(leader.close.to_numpy(dtype=float),index=li)
  lreturn=_continuous(lp,p['return_minutes'],'return');lmean=_continuous(lp,p['leader_trend_minutes'],'mean')
  source=pd.DataFrame({'observed_at':li+pd.Timedelta(minutes=p['publication_lag_minutes']),
                       'leader_return':lreturn.to_numpy(),'leader_above_trend':(lp>lmean).to_numpy(),
                       'leader_below_trend':(lp<lmean).to_numpy()})
  aligned=pd.merge_asof(pd.DataFrame({'available_at':index}),source.sort_values('observed_at'),left_on='available_at',right_on='observed_at',direction='backward',tolerance=pd.Timedelta(minutes=p['leader_stale_minutes']))
  aligned.index=index;local=_continuous(close,p['return_minutes'],'return');valid=aligned.leader_return.notna()
  le=valid&aligned.leader_above_trend.eq(True)&(aligned.leader_return>p['entry_return_threshold'])&(local<aligned.leader_return-p['catchup_threshold'])
  se=valid&aligned.leader_below_trend.eq(True)&(aligned.leader_return<-p['entry_return_threshold'])&(local>aligned.leader_return+p['catchup_threshold'])
  lx=(~valid)|(aligned.leader_return<=0)|aligned.leader_below_trend.eq(True)
  sx=(~valid)|(aligned.leader_return>=0)|aligned.leader_above_trend.eq(True)
 return _held(index,close,le,se,lx,sx,p)


# This is a market/size/momentum literature-inspired portfolio hypothesis, not a
# claim of replicating NBER factor returns in an eight-coin one-year universe.
FAMILIES['cross_sectional_momentum']={
 'description':'Daily7d momentum rank basket: top2 long, bottom2 short, middle cash',
 'parameters':{'lookback_minutes':10080,'expected_instruments':8,'long_count':2,'short_count':2,
               'decision_hour_utc':0,'decision_minute_utc':1,
               'tie_rule':'native instrument ID ascending; lowest IDs are lowest ranks on equal momentum'}}


def build_cross_signals(universe_bars,family='cross_sectional_momentum',scale=1.0):
 """Strictly synchronous signed rank basket; missing observations are rejected.

 All8 instruments need exactly the same continuous minute grid. No interpolation,
 forward fill, synthetic prices or current-survivor universe discovery occurs.
 Each daily00:01UTC decision uses all8 completed-bar closes and their causal7d
 returns. Top2 IDs in ascending (momentum, instrument ID) rank are long; bottom2
 short. Tied rank selection is deterministic, not evidence of return dispersion.
 The resulting signs persist until next daily decision, with no quantity resizing.
 Gross long/short sleeve counts balance at a rebalance; beta and drifting notional
 are not neutralized. The runner is responsible for native contract quantity units.
 """
 if family!='cross_sectional_momentum':raise ValueError('Use build_signals for individual instrument families')
 p=parameters(family,scale)
 required={'timestamp','instrument_id','duration_seconds','close'}
 if not required<=set(universe_bars):raise ValueError(f'Missing {sorted(required-set(universe_bars))}')
 if universe_bars.empty:raise ValueError('Eight synchronous instruments required')
 table=universe_bars[list(required)].copy()
 if table.instrument_id.isna().any():raise ValueError('Missing instrument identity')
 identities=sorted(table.instrument_id.astype(str).unique())
 if len(identities)!=p['expected_instruments']:raise ValueError('Cross momentum requires exactly8 frozen universe instruments')
 if not all(':perpetual:' in iid for iid in identities):raise ValueError('Native perpetual instrument IDs required')
 if not table.duration_seconds.eq(60).all():raise ValueError('Minute durations required')
 times=pd.to_datetime(table.timestamp,format='mixed')
 if not isinstance(times.dtype,pd.DatetimeTZDtype) or times.isna().any():raise ValueError('Nonmissing aware timestamps required')
 table['available_at']=(times.dt.tz_convert('UTC')+pd.Timedelta(minutes=1)).dt.as_unit('ns')
 if table.duplicated(['available_at','instrument_id']).any():raise ValueError('Duplicate instrument observations')
 prices=pd.to_numeric(table.close,errors='raise').to_numpy(dtype=float)
 if not np.isfinite(prices).all() or (prices<=0).any():raise ValueError('Positive finite closes required')
 table['close']=prices
 close=table.pivot(index='available_at',columns='instrument_id',values='close').reindex(columns=identities).sort_index()
 if close.isna().any().any():raise ValueError('Missing synchronized instrument observation; no price interpolation allowed')
 if not close.index.equals(close.index.floor('min')):raise ValueError('UTC minute-aligned timestamps required')
 if len(close)>1 and not close.index.to_series().diff().iloc[1:].eq(pd.Timedelta(minutes=1)).all():
  raise ValueError('Missing shared minute interval; strict coverage required')
 momentum=close.pct_change(p['lookback_minutes'],fill_method=None)
 valid=momentum.notna().all(axis=1).to_numpy()
 decision=(close.index.hour==p['decision_hour_utc'])&(close.index.minute==p['decision_minute_utc'])
 output=np.zeros(close.shape,dtype=np.int8);direction=np.zeros(len(identities),dtype=np.int8)
 scores=momentum.to_numpy(dtype=float)
 for i in range(len(close)):
  if decision[i] and valid[i]:
   # Stable sorting preserves ascending instrument IDs for exactly tied scores.
   rank=np.argsort(scores[i],kind='stable')
   direction=np.zeros(len(identities),dtype=np.int8)
   direction[rank[:p['short_count']]]=-1
   direction[rank[-p['long_count']:]]=1
  output[i]=direction
 return pd.DataFrame(output,index=close.index,columns=pd.Index(identities,name='instrument_id'))
