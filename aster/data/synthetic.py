"""Deterministic demonstration data, never represented as historical market evidence."""
import numpy as np
import pandas as pd

def generate(instruments, periods=2160, frequency='1h', seed=42):
    rng=np.random.default_rng(seed)
    start=pd.Timestamp('2024-01-01',tz='UTC')
    duration=int(pd.Timedelta(frequency).total_seconds())
    times=pd.date_range(start,periods=periods,freq=frequency)
    market=rng.normal(.00008,.006,periods)
    rows=[];funding=[]
    for j,spec in enumerate(instruments):
        initial=40000 if spec.base=='BTC' else 2200 if spec.base=='ETH' else 100+j*10
        ret=.7*market+rng.normal(0,.003,periods)
        closes=initial*np.exp(np.cumsum(ret));opens=np.r_[initial,closes[:-1]]
        width=rng.uniform(.001,.007,periods)
        marks=closes*(1+.0002*np.sin(np.arange(periods)/13))
        mark_opens=np.r_[initial,marks[:-1]]
        for i,t in enumerate(times):
            rows.append({'timestamp':t,'instrument_id':spec.id,'open':opens[i],'high':max(opens[i],closes[i])*(1+width[i]),
                'low':min(opens[i],closes[i])*(1-width[i]),'close':closes[i],'volume':rng.uniform(20,200),
                'duration_seconds':duration,'mark_price':marks[i],'mark_open':mark_opens[i],
                'index_price':closes[i],'exchange':spec.exchange,'symbol':spec.symbol,'market_type':spec.market_type})
            end=t+pd.Timedelta(seconds=duration)
            if spec.market_type=='perpetual' and end.hour%8==0 and end.minute==0 and end.second==0:
                funding.append({'timestamp':end,'instrument_id':spec.id,'funding_rate':.0001+.00015*np.sin(i/17),
                    'mark_price':marks[i]})
    return pd.DataFrame(rows),pd.DataFrame(funding)
