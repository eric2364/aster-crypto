"""Compare engineering strategies on identical synthetic data, no historical claims."""
from pathlib import Path
from dataclasses import asdict
import pandas as pd
from aster.cli import execute
from aster.exchanges.adapters import ADAPTERS
from aster.analytics import metrics

if __name__=='__main__':
    specs=[ADAPTERS['binance'].instrument('BTCUSDT','perpetual',base='BTC'),
           ADAPTERS['binance'].instrument('ETHUSDT','perpetual',base='ETH')]
    summaries=[]
    for name in ['buy_hold','ma','rsi','momentum','cross_momentum','breakout','funding','neutral','relative_value']:
        doc={'instruments':[asdict(s) for s in specs],'engine':{'initial_balances':{'binance':100000}},
            'strategy':{'name':name,'parameters':{'allocation':.15}},'data':{'synthetic':True,'periods':2160,'frequency':'1h'}}
        result=execute(doc,f'results/comparison/{name}')
        summaries.append({'strategy':name,**metrics(result.equity,result.trades,result.fills)})
    Path('results/comparison').mkdir(exist_ok=True,parents=True)
    pd.DataFrame(summaries).to_csv('results/comparison/strategies.csv',index=False)
