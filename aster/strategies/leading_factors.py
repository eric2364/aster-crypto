"""Preregistered leading-factor hypotheses; no return-driven parameter selection.

Long/cash outputs are timestamped at complete target-bar availability. External
BTC bars and funding settlements receive an additional one-minute observation
lag, with bounded stale-data tolerance. QQQ/macroeconomic/social data are excluded
until point-in-time inputs and receipt timestamps are verified.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from aster.strategies.minute_research import _state

FACTOR_FAMILIES={
 'btc_lead_momentum':{'description':'Completed BTC momentum with lagging target and trend confirmation',
  'parameters':{'return_minutes':60,'leader_trend_minutes':1440,'target_exit_minutes':360,'leader_threshold':.002,'catchup_threshold':.002,'entry_interval_minutes':30,'max_hold_minutes':360,'cooldown_minutes':60,'observation_lag_minutes':1,'stale_minutes':2}},
 'btc_lead_reversal':{'description':'Target overshoot after BTC selloff and observed BTC rebound',
  'parameters':{'return_minutes':60,'rebound_minutes':15,'leader_selloff_threshold':-.015,'target_selloff_threshold':-.02,'rebound_exit_threshold':-.005,'entry_interval_minutes':15,'max_hold_minutes':240,'cooldown_minutes':120,'observation_lag_minutes':1,'stale_minutes':2}},
 'funding_contrarian':{'description':'Published negative settlement funding with local rebound filter',
  'parameters':{'return_minutes':360,'rebound_minutes':60,'negative_funding_threshold':-.0001,'exit_funding_threshold':0.,'entry_return_floor':-.03,'exit_return_floor':-.05,'entry_interval_minutes':60,'max_hold_minutes':1440,'cooldown_minutes':120,'observation_lag_minutes':1,'funding_stale_minutes':720}}
}
FAMILIES=FACTOR_FAMILIES


def factor_parameters(family,scale=1.0):
 if family not in FACTOR_FAMILIES:raise ValueError(f'Unknown factor family: {family}')
 if not np.isfinite(scale) or scale<=0:raise ValueError('Positive finite scale required')
 p=FACTOR_FAMILIES[family]['parameters'].copy()
 fixed={'entry_interval_minutes','observation_lag_minutes','stale_minutes','funding_stale_minutes'}
 for key,value in p.items():
  if key.endswith('_minutes') and key not in fixed:p[key]=max(2,round(value*scale))
 return p


def _bar_frame(bars):
 if bars is None or not {'timestamp','close','duration_seconds'}<=set(bars):raise ValueError('Require timestamp, close, duration_seconds')
 if 'instrument_id' in bars and bars.instrument_id.nunique()>1:raise ValueError('Supply one instrument per bar frame')
 frame=bars.copy();dt=pd.to_datetime(frame.timestamp,format='mixed')
 if not isinstance(dt.dtype,pd.DatetimeTZDtype) or dt.isna().any():raise ValueError('Nonmissing aware timestamps required')
 if not frame.duration_seconds.eq(60).all():raise ValueError('Minute bars required')
 frame['end']=(dt.dt.tz_convert('UTC')+pd.Timedelta(minutes=1)).dt.as_unit('ns')
 frame=frame.sort_values('end').reset_index(drop=True)
 if frame.end.duplicated().any():raise ValueError('Duplicate bar timestamps')
 if not np.isfinite(frame.close.to_numpy(dtype=float)).all() or (frame.close<=0).any():raise ValueError('Positive finite close required')
 return frame


def _rolling_contiguous(close,periods,operation):
 # Do not calculate a minute-count return/mean across a missing source interval.
 groups=close.index.to_series().diff().ne(pd.Timedelta(minutes=1)).cumsum().to_numpy()
 output=pd.Series(np.nan,index=close.index)
 for _,segment in close.groupby(groups,sort=True):
  values=segment.pct_change(periods,fill_method=None) if operation=='return' else segment.rolling(periods,min_periods=periods).mean()
  output.loc[segment.index]=values
 return output


def _external_asof(target_index,features,lag_minutes,tolerance_minutes):
 frame=features.copy();frame['observed_at']=frame.index+pd.Timedelta(minutes=lag_minutes)
 frame=frame.reset_index(drop=True).sort_values('observed_at')
 target=pd.DataFrame({'available_at':target_index})
 joined=pd.merge_asof(target,frame,left_on='available_at',right_on='observed_at',direction='backward',tolerance=pd.Timedelta(minutes=tolerance_minutes))
 joined.index=target_index
 return joined


def build_factor_signals(bars,family,leader_bars=None,funding=None,qqq=None,scale=1.0):
 """Build fixed long/cash intent for one target; missing/stale external data => cash.

 Funding rows must be one matched instrument, with aware settlement timestamp and
 finite decimal funding_rate. This uses the rate as an explanatory observation;
 actual funding cashflows still belong to the engine's settlement ledger.
 """
 p=factor_parameters(family,scale)
 if qqq is not None:raise ValueError('QQQ factor inputs are not point-in-time verified or implemented')
 target=_bar_frame(bars)
 if target.empty:return pd.Series(dtype=np.int8,index=pd.DatetimeIndex([],tz='UTC'),name='signal')
 index=pd.DatetimeIndex(target.end,name='available_at');close=pd.Series(target.close.to_numpy(dtype=float),index=index)
 local_return=_rolling_contiguous(close,p['return_minutes'],'return')
 if family.startswith('btc_lead'):
  # A BTC target is an explicit cash sleeve, never evidence of self-leadership.
  symbols=target.instrument_id.astype(str).str.split(':').str[-1] if 'instrument_id' in target else target.get('symbol',pd.Series(dtype=str))
  if len(symbols) and symbols.eq('BTCUSDT').all():return pd.Series(0,index=index,dtype=np.int8,name='signal')
  if leader_bars is None:raise ValueError('BTC leader bars are required')
  leader=_bar_frame(leader_bars)
  leader_symbols=leader.instrument_id.astype(str).str.split(':').str[-1] if 'instrument_id' in leader else leader.get('symbol',pd.Series(dtype=str))
  if not len(leader_symbols) or not leader_symbols.eq('BTCUSDT').all():raise ValueError('BTC leader identity must be BTCUSDT')
  lindex=pd.DatetimeIndex(leader.end);price=pd.Series(leader.close.to_numpy(dtype=float),index=lindex)
  features=pd.DataFrame({'leader_return':_rolling_contiguous(price,p['return_minutes'],'return')})
  if family=='btc_lead_momentum':
   features['leader_trending']=price>_rolling_contiguous(price,p['leader_trend_minutes'],'mean')
  else:features['leader_rebound']=_rolling_contiguous(price,p['rebound_minutes'],'return')
  aligned=_external_asof(index,features,p['observation_lag_minutes'],p['stale_minutes'])
  valid=aligned.leader_return.notna()
  if family=='btc_lead_momentum':
   mean=_rolling_contiguous(close,p['target_exit_minutes'],'mean')
   entry=valid & aligned.leader_trending.eq(True) & (aligned.leader_return>p['leader_threshold']) & (local_return<aligned.leader_return-p['catchup_threshold'])
   exit=(~valid) | (aligned.leader_return<0) | (close<mean)
  else:
   local_mean=_rolling_contiguous(close,p['rebound_minutes'],'mean')
   valid &= aligned.leader_rebound.notna()
   entry=valid & (aligned.leader_return<p['leader_selloff_threshold']) & (local_return<p['target_selloff_threshold']) & (aligned.leader_rebound>0) & (close>local_mean)
   exit=(~valid) | (aligned.leader_rebound<p['rebound_exit_threshold']) | (close<local_mean)
 else:
  if funding is None or funding.empty:raise ValueError('Observed historical settlements are required for funding_contrarian')
  if 'funding_rate' not in funding or not ({'timestamp','available_at'}&set(funding)):raise ValueError('Funding requires timestamp/available_at and funding_rate')
  if 'instrument_id' in funding and funding.instrument_id.nunique()>1:raise ValueError('Filter funding to one matched target instrument')
  rates=funding.copy()
  if 'spot_instrument_id' in rates and 'instrument_id' in target:
   if set(rates.spot_instrument_id)!=set(target.instrument_id):raise ValueError('Funding spot identity must match target')
  elif 'instrument_id' in rates and 'instrument_id' in target:
   if set(rates.instrument_id.astype(str).str.split(':').str[-1])!=set(target.instrument_id.astype(str).str.split(':').str[-1]):raise ValueError('Funding symbol must match target')
  source_time=rates['available_at'] if 'available_at' in rates else rates['timestamp']
  times=pd.to_datetime(source_time,unit='ms',utc=True) if pd.api.types.is_numeric_dtype(source_time) else pd.to_datetime(source_time,format='mixed')
  if not isinstance(times.dtype,pd.DatetimeTZDtype) or times.isna().any():raise ValueError('Funding times must be nonmissing timezone-aware')
  if 'timestamp' in rates and 'available_at' in rates:
   settled=pd.to_datetime(rates.timestamp,unit='ms',utc=True) if pd.api.types.is_numeric_dtype(rates.timestamp) else pd.to_datetime(rates.timestamp,format='mixed')
   if not isinstance(settled.dtype,pd.DatetimeTZDtype) or settled.isna().any() or (times<settled).any():raise ValueError('Funding availability must not precede settlement')
  if times.duplicated().any():raise ValueError('Duplicate funding settlements')
  values=pd.to_numeric(rates.funding_rate,errors='raise').to_numpy(dtype=float)
  if not np.isfinite(values).all():raise ValueError('Finite funding rates required')
  features=pd.DataFrame({'observed_funding_rate':values},index=pd.DatetimeIndex(times.dt.tz_convert('UTC')).as_unit('ns'))
  aligned=_external_asof(index,features,p['observation_lag_minutes'],p['funding_stale_minutes'])
  valid=aligned.observed_funding_rate.notna()
  mean=_rolling_contiguous(close,p['rebound_minutes'],'mean')
  entry=valid & (aligned.observed_funding_rate<=p['negative_funding_threshold']) & (local_return>p['entry_return_floor']) & (close>mean)
  exit=(~valid) | (aligned.observed_funding_rate>=p['exit_funding_threshold']) | (local_return<p['exit_return_floor'])
 entry &= ~exit
 return _state(index,entry,exit,p['entry_interval_minutes'],p['cooldown_minutes'],p['max_hold_minutes'])
