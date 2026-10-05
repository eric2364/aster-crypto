"""Fixed trailing-year, training-only selection and locked holdout research.
Run from repository root: .venv/bin/python examples/minute_research/run.py
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aster.backtest.engine import Engine
from aster.backtest.models import Instrument, SimulationConfig
from aster.backtest.execution import floor_step
from aster.strategies.base import BaseStrategy
from aster.analytics import metrics, daily_returns, json_safe
from aster.reproducibility import export_result

START=pd.Timestamp('2025-10-05',tz='UTC')
TRAIN_END=pd.Timestamp('2026-04-05',tz='UTC')
HOLDOUT_START=pd.Timestamp('2026-07-05',tz='UTC')
END=pd.Timestamp('2026-10-05',tz='UTC')
SYMBOLS=['BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT']
SCALES=[.8,1.,1.2]

class EntryExitStrategy(BaseStrategy):
    """A signal transition submits once; filled entry units are held until exit."""
    version='minute-fixed-units-1'
    def __init__(self,signals):
        changed=signals.ne(signals.shift()).to_numpy()
        self.transitions=dict(zip(signals.index[changed],signals.to_numpy()[changed]))
    def on_bar(self,ctx,bar):
        value=self.transitions.get(ctx.now)
        if value is None:return
        spec=ctx.instruments[bar['instrument_id']]
        quantity=floor_step(ctx.portfolio.venue_equity(spec.exchange)*.95/bar['close'],spec.lot_size) if value else 0
        ctx.target(spec.id,quantity)

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(json_safe(obj),indent=2,allow_nan=False))

def job(args):
    family,symbol,scale,phase,start,end,stress,cache,out=args
    from aster.strategies.minute_research import build_signals, FAMILIES as PRICE_FAMILIES
    from aster.strategies.leading_factors import build_factor_signals
    root=Path(cache);destination=Path(out)/phase/family/f'{scale:g}'/('stress' if stress else 'base')/symbol
    runner_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    source=root/symbol/'bars.parquet'
    fingerprints={'runner':runner_hash,'data':hashlib.sha256(source.read_bytes()).hexdigest(),
        'instruments':hashlib.sha256((root/'instruments.json').read_bytes()).hexdigest(),
        'package':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('aster').rglob('*.py')}}
    if family not in PRICE_FAMILIES:
        fingerprints['leader']=hashlib.sha256((root/'BTCUSDT'/'bars.parquet').read_bytes()).hexdigest()
        fingerprints['funding']=hashlib.sha256((root/'funding'/f'{symbol}.parquet').read_bytes()).hexdigest()
    if (destination/'metrics.json').exists():
        prior=json.loads((destination/'metadata.json').read_text())
        if prior['parameters'].get('fingerprints')!=fingerprints:
            raise RuntimeError('Cached runner mismatch; use fresh output directory')
        return {'family':family,'symbol':symbol,'scale':scale,'phase':phase,'stress':stress,'path':str(destination),'metrics':json.loads((destination/'metrics.json').read_text())}
    records=json.loads((root/'instruments.json').read_text())
    spec=Instrument(**next(x for x in records if x['symbol']==symbol))
    spec=replace(spec,maker_bps=20 if stress else 10,taker_bps=20 if stress else 10)
    begin=pd.Timestamp(start);stop=pd.Timestamp(end)
    source=root/symbol/'bars.parquet';all_bars=pd.read_parquet(source)
    all_bars=all_bars[all_bars.timestamp<stop].copy()
    if family in PRICE_FAMILIES:
        signals=build_signals(all_bars,family,scale)
    else:
        leader=pd.read_parquet(root/'BTCUSDT'/'bars.parquet')
        leader=leader[leader.timestamp<stop].copy()
        observed_funding=pd.read_parquet(root/'funding'/f'{symbol}.parquet')
        observed_funding=observed_funding[observed_funding.available_at<stop].copy()
        signals=build_factor_signals(all_bars,family,leader_bars=leader,funding=observed_funding,scale=scale)
        fingerprints['leader']=hashlib.sha256((root/'BTCUSDT'/'bars.parquet').read_bytes()).hexdigest()
        fingerprints['funding']=hashlib.sha256((root/'funding'/f'{symbol}.parquet').read_bytes()).hexdigest()
    begin=pd.Timestamp(start);stop=pd.Timestamp(end)
    bars=all_bars[(all_bars.timestamp>=begin)&(all_bars.timestamp<stop)].copy()
    signals=signals.reindex(pd.DatetimeIndex(bars.timestamp+pd.to_timedelta(bars.duration_seconds,unit='s'))).fillna(0)
    # First test observation opens a position only after this test bar is complete.
    slip=8 if symbol in ('DOGEUSDT','PEPEUSDT') else 2 if symbol in ('BTCUSDT','ETHUSDT') else 5
    config=SimulationConfig(initial_balances={'binance':12500},leverage=1,max_gross_leverage=1,
        max_position_pct=.98,participation=.025 if stress else .05,slippage_bps=slip*(2 if stress else 1),
        execution_delay_bars=1 if stress else 0,funding_enabled=False,record_every=1 if phase=='holdout' else 60)
    result=Engine([spec],config).run(bars,EntryExitStrategy(signals))
    manifest=json.loads((root/symbol/'source_manifest.json').read_text())
    destination,score=export_result(result,destination,parameters={'family':family,'scale':scale,'phase':phase,
        'requested_start':str(begin),'requested_end_exclusive':str(stop),'signal_warmup':'earlier observed bars within the same year',
        'allocation':.95,'sizing':'fixed entry quantity held until exit','data_interval_seconds':60,
        'equity_sampling':'every minute in holdout; approximately hourly in training/validation',
        'fingerprints':fingerprints,'instrument_source':json.loads((root/'instrument_source_manifest.json').read_text()) if (root/'instrument_source_manifest.json').exists() else 'current exchangeInfo snapshot', 'research_runner_sha256':runner_hash,'normalized_parquet_sha256':hashlib.sha256(source.read_bytes()).hexdigest()},
        data_source='Binance official checksum-verified 1m spot archives',source_manifest=manifest)
    del all_bars,bars,result,signals
    return {'family':family,'symbol':symbol,'scale':scale,'phase':phase,'stress':stress,'path':str(destination),'metrics':score}

def aggregate(rows):
    frames=[pd.read_parquet(Path(r['path'])/'equity.parquet').set_index('timestamp') for r in rows]
    # Exact sum of segregated sleeve wallets; no capital transfer or rebalancing.
    numeric=frames[0].select_dtypes(include='number').columns
    combined=sum((f[numeric] for f in frames)).reset_index()
    combined['gross_leverage']=combined.gross_exposure/combined.equity
    combined['net_leverage']=combined.net_exposure/combined.equity
    combined['margin_utilization']=combined.margin_used/combined.equity
    trades=pd.concat([pd.read_parquet(Path(r['path'])/'trades.parquet') for r in rows],ignore_index=True)
    fills=pd.concat([pd.read_parquet(Path(r['path'])/'fills.parquet') for r in rows],ignore_index=True)
    return combined,metrics(combined,trades,fills)

def anchored_months(frame,start):
    series=frame.set_index('timestamp').equity
    bounds=[pd.Timestamp(start)+pd.DateOffset(months=k) for k in range(4)]
    values=[float(series.asof(t)) for t in bounds]
    return [values[i+1]/values[i]-1 for i in range(3)]

def bootstrap(frame):
    dated=frame.copy()
    dated['timestamp']=pd.to_datetime(dated.timestamp,utc=True).dt.as_unit('ns')
    final=pd.to_datetime(dated.timestamp,utc=True).max()
    # Endpoint marks belong to the last completed trading day, not next midnight.
    if final==final.normalize():
        dated.loc[dated.timestamp==final,'timestamp']=final-pd.Timedelta(microseconds=1)
    returns=daily_returns(dated)
    x=returns.dropna().to_numpy();rng=np.random.default_rng(42);n=len(x)
    if n<7:return {}
    starts=rng.integers(0,n,size=(10000,int(np.ceil(n/7))))
    indices=(starts[:,:,None]+np.arange(7))%n
    samples=x[indices.reshape(10000,-1)[:,:n]]
    totals=np.expm1(np.log1p(samples).sum(axis=1))
    return {'method':'circular7dayblockbootstrap;10000draws;seed42;conditional on observed holdout',
        'return_interval_95':np.quantile(totals,[.025,.975]).tolist(),
        'return_interval_bonferroni_8_families':np.quantile(totals,[.05/(2*8),1-.05/(2*8)]).tolist()}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cache',default='data_cache/minute-1y');parser.add_argument('--out',default='results/minute-study-1y');parser.add_argument('--workers',type=int,default=2);parser.add_argument('--training-only',action='store_true')
    args=parser.parse_args()
    from aster.strategies.minute_research import FAMILIES as PRICE_FAMILIES
    from aster.strategies.leading_factors import FACTOR_FAMILIES
    FAMILIES={**PRICE_FAMILIES,**FACTOR_FAMILIES}
    families=list(FAMILIES);root=Path(args.out)
    protocol={'start':str(START),'train_end':str(TRAIN_END),'holdout_start':str(HOLDOUT_START),'end_exclusive':str(END),
        'symbols':SYMBOLS,'families':FAMILIES,'scales':SCALES,'fee_bps':10,'stress_fee_bps':20,
        'selection':'one scale per family across all8symbols by training daily Sharpe; no holdout selection',
        'validation':'three fresh-wallet calendar-offset1month folds April5-May5,May5-June5,June5-July5',
        'publication_lag':'BTC complete bar/funding available_at plus1minute; no macro/sentiment input',
        'criteria':'positive pooled validation and holdout; >=2/3 positive holdout anchored months; Sharpe>=.5; minute drawdown<=.2; jointstresspositive; both holdoutneighborreturnspositive; >=5/8 symbolspositive',
        'limitations':['selected surviving universe is not survivorship-free','one year insufficient to establish durable edge','OHLCV execution approximation','training and validation drawdown sampled hourly','all families and trials disclosed','no repeated holdout tuning']}
    if not (root/'protocol.json').exists():dump(root/'protocol.json',protocol)
    elif json.loads((root/'protocol.json').read_text())!=json_safe(protocol):raise RuntimeError('Protocol changed; use fresh output directory')
    allrows=[]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs=[(family,symbol,scale,'training',str(START),str(TRAIN_END),False,args.cache,args.out) for family in families for scale in SCALES for symbol in SYMBOLS]
        for row in pool.map(job,jobs):
            allrows.append(row);print('training',row['family'],row['scale'],row['symbol'],flush=True)
        chosen={};training=[]
        for family in families:
            scores=[]
            for scale in SCALES:
                rows=[r for r in allrows if r['family']==family and r['scale']==scale]
                _,score=aggregate(rows);training.append({'family':family,'scale':scale,**score})
                scores.append((score.get('sharpe') if score.get('sharpe') is not None else -np.inf, -abs(scale-1), scale))
            chosen[family]=max(scores)[2]
        dump(root/'selection.json',{'chosen':chosen,'training_trials':training})
        if args.training_only:
            print('Training selection saved; holdout unopened.',flush=True)
            return
        # Selection file is written before any validation/holdout job is dispatched.
        jobs=[]
        for family,scale in chosen.items():
            for fold in range(3):
                begin=TRAIN_END+pd.DateOffset(months=fold);stop=TRAIN_END+pd.DateOffset(months=fold+1)
                jobs.extend((family,symbol,scale,f'validation{fold+1}',str(begin),str(stop),False,args.cache,args.out) for symbol in SYMBOLS)
            for neighbor in SCALES:
                jobs.extend((family,symbol,neighbor,'holdout',str(HOLDOUT_START),str(END),False,args.cache,args.out) for symbol in SYMBOLS)
            jobs.extend((family,symbol,scale,'holdout',str(HOLDOUT_START),str(END),True,args.cache,args.out) for symbol in SYMBOLS)
        for row in pool.map(job,jobs):
            allrows.append(row);print(row['phase'],row['family'],row['scale'],row['symbol'],'stress' if row['stress'] else 'base',flush=True)
    summaries=[];pooled=[]
    for family,scale in chosen.items():
        def rows_for(phase,s=scale,stress=False):return [r for r in allrows if r['family']==family and r['scale']==s and r['phase']==phase and r['stress']==stress]
        validation=[aggregate(rows_for(f'validation{k}'))[1] for k in (1,2,3)]
        rows=rows_for('holdout');equity,score=aggregate(rows)
        stressed,stress=aggregate(rows_for('holdout',stress=True))
        months=anchored_months(equity,HOLDOUT_START)
        neighbors={str(s):aggregate(rows_for('holdout',s))[1]['total_return'] for s in SCALES}
        positive_symbols=sum(r['metrics']['total_return']>0 for r in rows)
        validation_return=np.prod([1+v['total_return'] for v in validation])-1
        checks={'validation_positive':bool(validation_return>0),'holdout_positive':score['total_return']>0,
            'two_positive_months':sum(x>0 for x in months)>=2,'sharpe_at_least_half':(score.get('sharpe') or -np.inf)>=.5,
            'sampled_drawdown_within20pct':score['max_drawdown']<=.2,'jointstress_positive':stress['total_return']>0,
            'all_neighbor_returns_positive':all(v>0 for v in neighbors.values()),'broad_symbol_success':positive_symbols>=5}
        summaries.append({'family':family,'chosen_scale':scale,'validation_fold_metrics':validation,'validation_compounded_return':validation_return,
            'holdout':score,'stress':stress,'anchored_month_returns':months,'neighbor_holdout_returns':neighbors,
            'positive_symbols':positive_symbols,'symbols':{r['symbol']:r['metrics'] for r in rows},
            'bootstrap':bootstrap(equity),'checks':checks,'historical_hurdles_passed':all(checks.values())})
        destination=root/'pooled'/family;destination.mkdir(parents=True,exist_ok=True)
        equity.to_parquet(destination/'equity.parquet',index=False);stressed.to_parquet(destination/'stress_equity.parquet',index=False)
        for frame,scenario in [(equity,'base'),(stressed,'stress')]:
            pooled.extend({'family':family,'scenario':scenario,'timestamp':str(r.timestamp),'equity':r.equity} for r in frame.itertuples())
    dump(root/'summary.json',{'protocol':protocol,'families':summaries,'pass_count':sum(s['historical_hurdles_passed'] for s in summaries)})
    pd.DataFrame(pooled).to_csv(root/'pooled_equity.csv',index=False)
    dump(root/'all_trials.json',allrows)
    print('Complete:',root/'summary.json',flush=True)

if __name__=='__main__':main()
