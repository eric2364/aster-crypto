"""Second-review adversaries for joint-wallet audit; synthetic data only."""
import copy
from dataclasses import asdict
import pandas as pd
import pytest
from aster.backtest.engine import Engine
from examples.funding_rank.run import SnapshotObserver, terminal_status
from examples.funding_rank.strategy import FundingRankPortfolio
from audit import verify_funding_rank_outputs as a
from test_funding_rank_execution import START,catalog,config,candles,feature_frame
from test_funding_rank_financial_audit import evidence


def engine_evidence(bars,stop=None,strategy_class=FundingRankPortfolio):
    specs=list(catalog().values());cfg=config();engine=Engine(specs,cfg);observer=SnapshotObserver(engine)
    engine.portfolio.snapshot=observer
    fund=pd.DataFrame({'timestamp':pd.Series([],dtype='datetime64[ns, UTC]'),
        'instrument_id':pd.Series([],dtype=str),'funding_rate':pd.Series([],dtype=float),
        'mark_price':pd.Series([],dtype=float)})
    result=engine.run(bars,strategy_class(feature_frame(),stop or START+pd.Timedelta(days=30)),fund)
    tables={name:getattr(result,name) for name in a.LEDGERS}
    sources={s.id:bars.loc[bars.instrument_id.eq(s.id)].reset_index(drop=True) for s in specs}
    return (tables,pd.DataFrame(observer.rows),sources,fund,[asdict(s) for s in specs],asdict(cfg)),observer,result


def test_forced_cross_liquidation_replays_all_legs_cash_fees_not_net_collateral():
    bars=candles();shock=(bars.timestamp>=START+pd.Timedelta(minutes=8))&bars.instrument_id.str.contains('BTCUSDT|ETHUSDT')
    bars.loc[shock,['open','high','low','close','mark_open','mark_price']]=1000.
    args,observer,result=engine_evidence(bars)
    assert result.events.type.eq('LIQUIDATION').sum()==4 and result.positions.empty
    state,_=a.reconstruct(*args,START,START+pd.Timedelta(minutes=16))
    assert all(q==0 for q in state.q.values()) and state.liqfees>0
    assert state.cash['binance']==pytest.approx(result.equity.cash.iloc[-1])
    pre=args[0]['equity'].loc[args[0]['equity'].timestamp.eq(START+pd.Timedelta(minutes=7))].iloc[0]
    assert pre.margin_used>24000 and abs(pre.net_exposure)<100


def test_drop_then_reseal_close_trade_rejected_by_independent_replay():
    args=list(evidence(failed_leg=True));tables=copy.deepcopy(args[0]);assert len(tables['trades'])>=1
    tables['trades']=tables['trades'].iloc[1:].copy();args[0]=tables
    with pytest.raises(AssertionError,match='Trade count'):a.reconstruct(*args,START,START+pd.Timedelta(minutes=16))


def test_resealed_closed_trade_funding_and_net_pnl_rejected():
    args=list(evidence(failed_leg=True));tables=copy.deepcopy(args[0]);assert len(tables['trades'])>=1
    tables['trades'].loc[tables['trades'].index[0],'funding_pnl']+=10
    tables['trades'].loc[tables['trades'].index[0],'net_pnl']+=10;args[0]=tables
    with pytest.raises(AssertionError,match='Trade'):a.reconstruct(*args,START,START+pd.Timedelta(minutes=16))


def test_cancel_before_fill_at_same_clock_rejected_even_if_time_equal():
    args=list(evidence());tables=copy.deepcopy(args[0]);events=tables['events'].copy()
    filled=events.index[events.type.eq('ORDER_FILLED')][0];row=events.loc[filled].copy()
    row['type']='ORDER_CANCELLED';row['reason']='synthetic_before_fill'
    tables['events']=pd.concat([events.loc[:filled-1],pd.DataFrame([row]),events.loc[filled:]],ignore_index=True);args[0]=tables
    with pytest.raises(AssertionError,match='cancellation'):a.reconstruct(*args,START,START+pd.Timedelta(minutes=16))


def test_healthy_forced_fill_label_rejected_without_actual_cross_insolvency():
    args=list(evidence());tables=copy.deepcopy(args[0]);tables['fills'].loc[0,'exit_reason']='liquidation';args[0]=tables
    with pytest.raises(AssertionError,match='forced fill'):a.reconstruct(*args,START,START+pd.Timedelta(minutes=16))


def test_end_autocancel_does_not_erase_pre_end_live_order_evidence():
    class SyntheticExit(FundingRankPortfolio):
        def on_bars(self,ctx,bars):
            super().on_bars(ctx,bars)
            if ctx.now==START+pd.Timedelta(minutes=6) and self.active:
                self._close(ctx,'synthetic_exit_request')
    volumes={(m,'DOGEUSDT'):0 for m in range(5,16)}
    args,observer,result=engine_evidence(candles(volumes),strategy_class=SyntheticExit)
    assert observer.last_orders and result.events.loc[result.events.type.eq('ORDER_CANCELLED'),'reason'].eq('end_of_data').any()
    state,_=a.reconstruct(*args,START,START+pd.Timedelta(minutes=16))
    assert state.live_order_count==len(observer.last_orders)
    assert not terminal_status(observer.rows[-1],observer.last_orders)['terminal_flat_resolved']
    changed=args[1].copy();changed.loc[changed.index[-1],'live_order_count']=0
    with pytest.raises(AssertionError,match='live_order_count'):
        a.reconstruct(args[0],changed,*args[2:],START,START+pd.Timedelta(minutes=16))


def test_auditor_graph_has_no_production_or_strategy_imports():
    import ast
    from pathlib import Path
    tree=ast.parse(Path(a.__file__).read_text());imports=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):imports += [v.name for v in node.names]
        elif isinstance(node,ast.ImportFrom):imports.append(node.module or '')
    assert not any(n=='aster' or n.startswith('aster.') or n.startswith('examples.') for n in imports)
