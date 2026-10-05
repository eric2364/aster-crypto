from itertools import product
import pandas as pd
from aster.backtest.engine import Engine
from aster.analytics.metrics import metrics

WARNING='Historical parameter selection overfits. Use untouched holdout, sensitivity, costs and multiple regimes.'

def grid_search(instruments,config,bars,strategy_factory,grid,funding=None,objective='sharpe'):
    keys=list(grid);rows=[]
    for values in product(*(grid[k] for k in keys)):
        params=dict(zip(keys,values))
        result=Engine(instruments,config).run(bars,strategy_factory(**params),funding)
        score=metrics(result.equity,result.trades,result.fills)
        rows.append({'parameters':params,**score})
    frame=pd.DataFrame(rows)
    if objective not in frame:raise ValueError('Unknown objective')
    frame.attrs['warning']=WARNING
    return frame.sort_values(objective,ascending=False,na_position='last')

def walk_forward(instruments,config,bars,strategy_factory,grid,train_days=180,test_days=30,funding=None,objective='sharpe'):
    if min(train_days,test_days)<=0:raise ValueError('Positive windows required')
    start=pd.to_datetime(bars.timestamp,utc=True).min();end=pd.to_datetime(bars.timestamp,utc=True).max()
    times=pd.to_datetime(bars.timestamp,utc=True);out=[]
    while start+pd.Timedelta(days=train_days)<end:
        split=start+pd.Timedelta(days=train_days);stop=split+pd.Timedelta(days=test_days)
        train=bars[(times>=start)&(times<split)].copy();test=bars[(times>=split)&(times<stop)].copy()
        # Never include a training candle whose close is beyond the split.
        train=train[pd.to_datetime(train.timestamp,utc=True)+pd.to_timedelta(train.duration_seconds,unit='s')<=split]
        test=test[pd.to_datetime(test.timestamp,utc=True)+pd.to_timedelta(test.duration_seconds,unit='s')<=stop]
        if train.empty or test.empty:break
        ranking=grid_search(instruments,config,train,strategy_factory,grid,funding,objective)
        valid=ranking.dropna(subset=[objective])
        if valid.empty:raise ValueError('No finite training objective; increase training duration')
        params=valid.iloc[0].parameters
        result=Engine(instruments,config).run(test,strategy_factory(**params),funding)
        out.append({'train_start':start,'train_end':split,'test_start':split,'test_end':stop,
            'parameters':params,'in_sample':valid.iloc[0].to_dict(),'out_of_sample':metrics(result.equity,result.trades,result.fills),
            'result':result})
        start+=pd.Timedelta(days=test_days)
    return out

def robustness(instruments,config,bars,strategy_factory,parameters,funding=None):
    from dataclasses import replace
    scenarios={'baseline':config,'double_slippage':replace(config,slippage_bps=config.slippage_bps*2),
        'half_liquidity':replace(config,participation=config.participation/2),
        'one_bar_delay':replace(config,execution_delay_bars=config.execution_delay_bars+1)}
    rows=[]
    for name,cfg in scenarios.items():
        r=Engine(instruments,cfg).run(bars,strategy_factory(**parameters),funding)
        rows.append({'scenario':name,**metrics(r.equity,r.trades,r.fills)})
    costly=[replace(s,maker_bps=s.maker_bps*2,taker_bps=s.taker_bps*2) for s in instruments]
    r=Engine(costly,config).run(bars,strategy_factory(**parameters),funding)
    rows.append({'scenario':'double_fees',**metrics(r.equity,r.trades,r.fills)})
    return pd.DataFrame(rows)
