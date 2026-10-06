"""Independent trajectory audit on synthetic shared-wallet executions."""
import copy
from dataclasses import asdict
import pandas as pd
import pytest
from aster.backtest.engine import Engine
from examples.funding_rank.run import SnapshotObserver
from examples.funding_rank.strategy import FundingRankPortfolio
from audit import verify_funding_rank_outputs as auditor
from test_funding_rank_execution import START, catalog, config, candles, feature_frame


def evidence(delay=0, failed_leg=False):
    specs=list(catalog().values())
    volumes={(m,'DOGEUSDT'):0 for m in range(16)} if failed_leg else None
    bars=candles(volumes)
    funding=pd.DataFrame([dict(timestamp=START+pd.Timedelta(minutes=6),instrument_id=s.id,
        funding_rate=.0001,mark_price=.01 if s.symbol=='1000PEPEUSDT' else 100) for s in specs]+[
        dict(timestamp=START+pd.Timedelta(minutes=8,milliseconds=2),instrument_id=specs[0].id,
             funding_rate=-.0002,mark_price=101)])
    engine=Engine(specs,config(delay));observer=SnapshotObserver(engine)
    engine.portfolio.snapshot=observer
    result=engine.run(bars,FundingRankPortfolio(feature_frame(),START+pd.Timedelta(days=30)),funding)
    tables={name:getattr(result,name) for name in auditor.LEDGERS}
    return tables,pd.DataFrame(observer.rows),{s.id:bars.loc[bars.instrument_id.eq(s.id)].reset_index(drop=True) for s in specs},funding,[asdict(s) for s in specs],asdict(config(delay))


@pytest.mark.parametrize('delay,failed',[(0,False),(1,False),(0,True),(1,True)])
def test_independent_full_wallet_replay_real_synthetic_engine(delay,failed):
    arguments=evidence(delay,failed)
    state,preopen=auditor.reconstruct(*arguments,START,START+pd.Timedelta(minutes=16))
    assert len(preopen)==18 and state.fees>0
    assert state.cash['binance']==pytest.approx(arguments[0]['equity'].cash.iloc[-1])
    assert sum(state.q.values())==pytest.approx(0 if failed else sum(arguments[0]['positions'].quantity))


@pytest.mark.parametrize('mutation',['cash','margin','reserve','mark','native','funding_sign','funding_clock','quantity','fee','price','volume','live_orders','source_rate','source_mark'])
def test_resealed_false_financial_evidence_rejected(mutation):
    tables,exposure,bars,funding,specs,cfg=evidence()
    tables=copy.deepcopy(tables);exposure=exposure.copy();funding=funding.copy();bars=copy.deepcopy(bars)
    if mutation=='cash':tables['equity'].loc[6,'cash']+=1
    elif mutation=='margin':tables['equity'].loc[6,'margin_used']=0
    elif mutation=='reserve':exposure.loc[6,'entry_collateral_field_DOGEUSDT']+=1
    elif mutation=='mark':exposure.loc[6,'mark_PEPEUSDT']*=1000
    elif mutation=='native':tables['fills'].loc[0,'instrument_id']='binance:perpetual:PEPEUSDT'
    elif mutation=='funding_sign':tables['funding'].loc[0,'funding_payment']*=-1
    elif mutation=='funding_clock':tables['funding'].loc[0,'timestamp']+=pd.Timedelta(seconds=1)
    elif mutation=='quantity':tables['fills'].loc[0,'quantity']+=1
    elif mutation=='fee':tables['fills'].loc[0,'fee']+=1
    elif mutation=='price':tables['fills'].loc[0,'price']+=1
    elif mutation=='volume':
        key=tables['fills'].instrument_id.iloc[0];bars[key].loc[4,'volume']=0
    elif mutation=='live_orders':exposure.loc[6,'live_order_count']+=1
    elif mutation=='source_rate':funding.loc[0,'funding_rate']*=2
    else:funding.loc[0,'mark_price']*=2
    with pytest.raises((AssertionError,KeyError)):
        auditor.reconstruct(tables,exposure,bars,funding,specs,cfg,START,START+pd.Timedelta(minutes=16))
