from pathlib import Path
import pandas as pd
from aster.backtest.models import SimulationConfig
from aster.exchanges.adapters import ADAPTERS
from aster.data.synthetic import generate
from aster.strategies.examples import MovingAverage
from aster.optimization.search import grid_search,walk_forward,robustness

if __name__=='__main__':
    instruments=[ADAPTERS['binance'].instrument('BTCUSDT','perpetual')]
    cfg=SimulationConfig();bars,funding=generate(instruments,periods=2160)
    grid={'fast':[4,8],'slow':[16,24],'allocation':[.15]}
    ranking=grid_search(instruments,cfg,bars,MovingAverage,grid,funding)
    root=Path('results/research');root.mkdir(parents=True,exist_ok=True)
    ranking.to_csv(root/'grid.csv',index=False)
    folds=walk_forward(instruments,cfg,bars,MovingAverage,grid,train_days=30,test_days=15,funding=funding)
    pd.DataFrame([{k:v for k,v in f.items() if k!='result'} for f in folds]).to_csv(root/'walk_forward.csv',index=False)
    robustness(instruments,cfg,bars,MovingAverage,{'fast':8,'slow':24,'allocation':.15},funding).to_csv(root/'robustness.csv',index=False)
    print(f'{len(ranking)} grid trials; {len(folds)} out-of-sample folds. {ranking.attrs["warning"]}')
