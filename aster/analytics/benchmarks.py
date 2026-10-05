"""Frictionless reference indices; executable BuyHold strategies are separate."""
import pandas as pd

def benchmarks(bars, initial_equity=100000):
    df=bars.copy();df['timestamp']=pd.to_datetime(df.timestamp,utc=True)
    df['available_at']=df.timestamp+pd.to_timedelta(df.duration_seconds,unit='s')
    series={}
    seen=set()
    for iid,g in df.groupby('instrument_id'):
        symbol=g.symbol.iloc[0] if 'symbol' in g else iid
        base='BTC' if 'BTC' in symbol else 'ETH' if 'ETH' in symbol else symbol
        if base in seen:continue
        seen.add(base);g=g.sort_values('timestamp')
        prices=pd.Series(g.close.to_numpy(),index=pd.DatetimeIndex(g.available_at))
        baseline=pd.Series([g.open.iloc[0]],index=pd.DatetimeIndex([g.timestamp.iloc[0]]))
        series[f'{base} Buy & Hold']=pd.concat([baseline,prices])/g.open.iloc[0]*initial_equity
    frame=pd.DataFrame(series).sort_index().ffill()
    if len(frame.columns):frame['Equal Weight']=frame.mean(axis=1)
    frame['Cash']=initial_equity
    return frame.rename_axis('timestamp').reset_index()

def denominate(equity, quote_price):
    """As-of conversion using observed reference prices; never backward-fill."""
    left=equity.copy();right=quote_price[['timestamp','price']].copy()
    left.timestamp=pd.to_datetime(left.timestamp,utc=True);right.timestamp=pd.to_datetime(right.timestamp,utc=True)
    merged=pd.merge_asof(left.sort_values('timestamp'),right.sort_values('timestamp'),on='timestamp',direction='backward')
    if merged.price.isna().any() or (merged.price<=0).any():raise ValueError('Positive observed denomination prices required')
    merged.equity=merged.equity/merged.price
    return merged.drop(columns=['price'])
