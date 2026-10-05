"""Exploratory signed perpetual hypotheses on a previously examined historical year.

Freeze/audit first. Training chooses one common duration scale per hypothesis.
The reused evaluation window is explicitly NOT an untouched holdout.
python examples/minute_directional/run.py --freeze-only
python examples/minute_directional/run.py --workers 4
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

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from aster.analytics import metrics, daily_returns, json_safe
from aster.backtest.engine import Engine
from aster.backtest.execution import floor_step
from aster.backtest.models import Instrument, SimulationConfig
from aster.reproducibility import export_result, verify_ledgers
from aster.strategies.base import BaseStrategy
from examples.minute_directional.signals import FAMILIES, build_signals, build_cross_signals, parameters

START=pd.Timestamp('2025-10-05',tz='UTC')
TRAIN_END=pd.Timestamp('2026-04-05',tz='UTC')
EVALUATION_START=pd.Timestamp('2026-07-05',tz='UTC')
END=pd.Timestamp('2026-10-05',tz='UTC')
SYMBOLS=['BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT']
SCALES=[.8,1.,1.2]


def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(json_safe(value),indent=2,allow_nan=False)+'\n')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_identity():
    return {'runner':digest(__file__),'signals':digest(Path(__file__).with_name('signals.py')),
            'package':{str(path):digest(path) for path in sorted(Path('aster').rglob('*.py'))}}


def freeze(out):
    root=Path(out)
    protocol={'research_status':'EXPLORATORY: evaluation year was already examined in thirteen prior policies; not untouched, no non-overfit proof',
      'motivation':'symmetric slower long/short price hypotheses motivated by training-regime direction and prior research limitations; original models remain unchanged',
      'families':FAMILIES,'correlation_warning':'trend variants overlap; six hypotheses are not six independent economic edges',
      'cross_sectional_portfolio':'daily7day ranktop2long/bottom2short/middlecash across all8nativeperpetual markets; balanced initial long/short entry notional, not beta-neutral or drift-rebalanced thereafter',
      'scales':SCALES,'scale_definition':'duration/cooldown/holding windows only; decision schedules and entry thresholds fixed',
      'selection':'one common scale per hypothesis across eight pooled sleeves maximizing training daily Sharpe; ties prefer1 then larger scale',
      'start':str(START),'training_end':str(TRAIN_END),'evaluation_start':str(EVALUATION_START),'end_exclusive':str(END),
      'validation':'three fresh-wallet monthly folds April5-May5,May5-June5,June5-July5; no selection on validation',
      'symbols':SYMBOLS,'pooled_initial_capital':100000,'segregated_sleeve_capital':12500,
      'entry_notional_fraction':.25,'quantity':'fixed native perpetual base-unit quantity at entry; no minute rebalancing;1000PEPE remains its native1000PEPE units',
      'leverage':1,'margin_mode':'isolated','max_gross_leverage':1,'base_taker_bps':5,
      'slippage_bps':{'BTCUSDT':2,'ETHUSDT':2,'DOGEUSDT':8,'PEPEUSDT':8,'other':5},'participation':.05,
      'funding':'actual separate settlement cash flows from timestamped native-contract funding/mark history; includes boundary settlement if present',
      'leader':'completed BTC perpetual observations plus one extra minute publication lag; backward-only as-of and two-minute stale tolerance',
      'terminal':'open positions marked at the actual final observation, matching original spot research convention; no artificial terminal orders',
      'indicative_exit_reserve':'diagnostic only: final open marked notional times assumed takerfee+configured adverse slippage; no fabricated trade/cashflow or guarantee of executable volume',
      'equity_sampling':'minute/funding clocks for final evaluation; approximately hourly training/validation; pooledunion clock with prior-only sleeve carry-forward',
      'stress':'double fee/slippage, add one minute order delay, halve volume participation',
      'neighbors':'all three scales reported on final evaluation; never use neighbors to revise training selection',
      'criteria':'positive compounded validation/final evaluation/jointstress and corresponding indicative-reserve returns; >=2/3positive anchored months; Sharpe>=.5; minute drawdown<=.2; all3neighborreturnspositive including indicative-reserve diagnostic; no liquidation in validation/chosen/neighbor/stress cases',
      'breadth_criteria':'five scalar hypotheses require>=5of8profitable evaluation sleeves; rankedlong/shortbasket requires actualfills across>=4distinct assets because hedging legs may lose, while all8assetPnLs remain disclosed',
      'multiple_testing':'19 policy/hypothesis comparisons cumulatively disclosed; conservative conditional bootstrap tails .05/38 and1-.05/38',
      'limitations':['reused historical evaluation introduces research adaptation bias','selected surviving assets','current instrument rules approximate history','minute marks omit intraminute liquidation paths','OHLCV volume fills approximate market microstructure','historical hurdle pass is not durable future profitability']}
    path=root/'protocol.json'
    if path.exists() and json.loads(path.read_text())!=json_safe(protocol):raise RuntimeError('Frozen economic protocol changed; new disclosed batch required')
    if not path.exists():dump(path,protocol)
    lock={**source_identity(),'protocol':digest(path)}
    locked=root/'source_lock.json'
    if locked.exists() and json.loads(locked.read_text())!=lock:
        raise RuntimeError('Frozen code changed; preserve executed source and use explicit analysis recovery, never silently overwrite outcomes')
    if not locked.exists():dump(locked,lock)
    for source in [Path(__file__),Path(__file__).with_name('signals.py')]:
        copy=root/('executed_'+source.name)
        if not copy.exists():copy.write_bytes(source.read_bytes())
        if digest(copy)!=digest(source):raise RuntimeError('Executed source archive mismatch')
    return protocol


class FixedDirectional(BaseStrategy):
    version='exploratory-fixed-quarter-notional-1'
    def __init__(self,signals,stop):
        if not signals.index.is_unique:raise ValueError('Signals must have unique availability times')
        if not isinstance(signals.index.dtype,pd.DatetimeTZDtype):raise ValueError('UTC-aware availability times required')
        if not signals.isin([-1,0,1]).all():raise ValueError('Only signed -1/0/+1 intents supported')
        changed=signals.ne(signals.shift()).to_numpy()
        self.transitions=dict(zip(signals.index[changed],signals.to_numpy()[changed]))
        self.stop=stop
    def on_bar(self,ctx,bar):
        iid=bar['instrument_id']
        direction=self.transitions.get(ctx.now)
        if direction is None:return
        spec=ctx.instruments[iid]
        if direction:
            value=max(0,ctx.portfolio.venue_equity(spec.exchange))*.25/bar['close']
            quantity=floor_step(value,spec.lot_size)*int(direction)
        else:quantity=0
        ctx.target(iid,quantity)


def exit_reserve(result):
    fees=slippage=0.
    instruments={spec.id:spec for spec in result.instruments}
    for position in result.positions.itertuples():
        notional=abs(position.quantity)*position.mark_price
        fees+=notional*instruments[position.instrument_id].taker_bps/10000
        slippage+=notional*result.config.slippage_bps/10000
    final=float(result.equity.iloc[-1].equity);initial=sum(result.config.initial_balances.values())
    return {'indicative_exit_fee_reserve':fees,'indicative_exit_slippage_reserve':slippage,
            'indicative_exit_reserve_total':fees+slippage,'final_equity_after_indicative_exit_reserve':final-fees-slippage,
            'return_after_indicative_exit_reserve':(final-fees-slippage)/initial-1}


def cross_features(cache,out,stop,scale):
    """Precompute one causal matrix per cutoff/scale, with all8 source identities."""
    root=Path(cache);stop=pd.Timestamp(stop)
    paths=[root/symbol/'bars.parquet' for symbol in SYMBOLS]
    identity={'stop_exclusive':str(stop),'scale':scale,'signals_source':digest(Path(__file__).with_name('signals.py')),
              'bar_sources':{str(path):digest(path) for path in paths}}
    name=f'cross_{stop.strftime("%Y%m%d")}_{scale:g}'
    target=Path(out)/'signal_cache'/f'{name}.parquet';manifest=target.with_suffix('.json')
    if target.exists():
        if not manifest.exists():raise RuntimeError('Crossfeature source manifest missing')
        stored=json.loads(manifest.read_text())
        if {k:v for k,v in stored.items() if k!='matrix_sha256'}!=identity:raise RuntimeError('Crossfeature source mismatch')
        if stored.get('matrix_sha256')!=digest(target):raise RuntimeError('Crossfeature cached values changed')
        return target
    frames=[]
    for path in paths:
        frame=pd.read_parquet(path,columns=['timestamp','duration_seconds','close','instrument_id'])
        frames.append(frame[frame.timestamp<stop].copy())
    matrix=build_cross_signals(pd.concat(frames,ignore_index=True),scale=scale)
    target.parent.mkdir(parents=True,exist_ok=True);matrix.to_parquet(target)
    dump(manifest,{**identity,'matrix_sha256':digest(target)});return target


def job(args):
    family,symbol,scale,phase,begin,stop,stress,cache,out=args
    root=Path(cache);begin=pd.Timestamp(begin);stop=pd.Timestamp(stop)
    destination=Path(out)/phase/family/f'{scale:g}'/('stress' if stress else 'base')/symbol
    mapping=next(x for x in json.loads((root/'cross_mapping.json').read_text())['mapping'] if x['spot_symbol']==symbol)
    sources=[root/symbol/'bars.parquet',root/symbol/'funding.parquet',root/'instruments.json',root/'cross_mapping.json']
    fingerprints={**source_identity(),'data':{str(p):digest(p) for p in sources}}
    if family=='btc_conditioned_alt_lag':fingerprints['data'][str(root/'BTCUSDT'/'bars.parquet')]=digest(root/'BTCUSDT'/'bars.parquet')
    if family=='cross_sectional_momentum':
        for other in SYMBOLS:fingerprints['data'][str(root/other/'bars.parquet')]=digest(root/other/'bars.parquet')
        matrix_path=Path(out)/'signal_cache'/f'cross_{stop.strftime("%Y%m%d")}_{scale:g}.parquet'
        matrix_manifest=matrix_path.with_suffix('.json')
        if not matrix_path.exists() or not matrix_manifest.exists():raise RuntimeError('Precompute verified crossfeature matrix before job dispatch')
        expected=json.loads(matrix_manifest.read_text())
        if expected['signals_source']!=fingerprints['signals'] or expected['stop_exclusive']!=str(stop) or expected['scale']!=scale:
            raise RuntimeError('Crossfeature metadata mismatch')
        if any(fingerprints['data'].get(name)!=value for name,value in expected['bar_sources'].items()):raise RuntimeError('Crossfeature universe-source mismatch')
        if expected.get('matrix_sha256')!=digest(matrix_path):raise RuntimeError('Crossfeature cached values changed')
        fingerprints['cross_feature_matrix']=digest(matrix_path)
        fingerprints['cross_feature_manifest']=digest(matrix_manifest)
    if (destination/'metrics.json').exists():
        prior=json.loads((destination/'metadata.json').read_text())['parameters']
        if prior['fingerprints']!=fingerprints:raise RuntimeError('Cached directional result fingerprint mismatch')
        return dict(family=family,symbol=symbol,scale=scale,phase=phase,stress=stress,path=str(destination),metrics=json.loads((destination/'metrics.json').read_text()))
    spec=Instrument(**next(x for x in json.loads((root/'instruments.json').read_text()) if x['id']==mapping['perpetual_instrument_id']))
    spec=replace(spec,maker_bps=10 if stress else 5,taker_bps=10 if stress else 5)
    all_bars=pd.read_parquet(sources[0]);all_bars=all_bars[all_bars.timestamp<stop].copy()
    if set(all_bars.instrument_id)!={spec.id}:raise ValueError('Native perpetual source identity mismatch')
    funding=pd.read_parquet(sources[1]);funding=funding[(funding.timestamp>=begin)&(funding.timestamp<=stop)].copy()
    if set(funding.instrument_id)!={spec.id}:raise ValueError('Native funding quantity identity mismatch')
    leader=None
    if family=='btc_conditioned_alt_lag':
        leader=pd.read_parquet(root/'BTCUSDT'/'bars.parquet');leader=leader[leader.timestamp<stop].copy()
    if family=='cross_sectional_momentum':
        signals=pd.read_parquet(matrix_path)[spec.id]
    else:signals=build_signals(all_bars,family,scale,leader_bars=leader)
    bars=all_bars[all_bars.timestamp>=begin].copy()
    clock=pd.DatetimeIndex(bars.timestamp+pd.to_timedelta(bars.duration_seconds,unit='s'))
    signals=signals.reindex(clock).fillna(0).astype(np.int8)
    slip=2 if symbol in ['BTCUSDT','ETHUSDT'] else 8 if symbol in ['DOGEUSDT','PEPEUSDT'] else 5
    config=SimulationConfig(initial_balances={'binance':12500},leverage=1,margin_mode='isolated',max_gross_leverage=1,
        max_position_pct=.5,slippage_bps=slip*(2 if stress else 1),participation=.025 if stress else .05,
        execution_delay_bars=1 if stress else 0,record_every=1 if phase=='holdout' else 60)
    result=Engine([spec],config).run(bars,FixedDirectional(signals,stop),funding=funding)
    verify_ledgers(result)
    reserve=exit_reserve(result)
    manifest=json.loads((root/symbol/'source_manifest.json').read_text())
    _,score=export_result(result,destination,parameters={'family':family,'scale':scale,'family_parameters':parameters(family,scale),
        'phase':phase,'stress':stress,'fingerprints':fingerprints,'research_status':'exploratory reused historical evaluation',
        'entry_notional_fraction':.25,'native_perpetual_base':spec.base,'source_base_units_per_quantity':mapping['spot_base_units_per_perpetual_quantity_unit'],
        'quantity_policy':'fixed at each direction change, held through subsequent unchanged signals',
        'warmup':'earlier observations within same fixed year; no future signal inputs',
        'requested_start':str(begin),'requested_end_exclusive':str(stop),'terminal_open_position_count':len(result.positions),
        'terminal_convention':'actual open inventory marked, no forced close orders','indicative_exit_reserve':reserve,
        'funding_settlement_cutoff':'inclusive actual settlement timestamp<=end','equity_sampling_minutes':1 if phase=='holdout' else 60},
        data_source='Actual official Binance one-minute linear perpetual trade bars, mark observations and settled native-contract funding',
        source_manifest={'market':manifest,'mapping':mapping,'instrument_source':json.loads((root/'instrument_source_manifest.json').read_text())})
    score.update(reserve)
    score['liquidation_event_count']=int(result.events.type.eq('LIQUIDATION').sum()) if 'type' in result.events else 0
    dump(destination/'metrics.json',score)
    return dict(family=family,symbol=symbol,scale=scale,phase=phase,stress=stress,path=str(destination),metrics=score)


def aggregate(rows):
    if not rows:raise ValueError('At least one sleeve required')
    frames=[pd.read_parquet(Path(row['path'])/'equity.parquet').set_index('timestamp') for row in rows]
    clock=frames[0].index
    for frame in frames[1:]:clock=clock.union(frame.index)
    clock=clock.sort_values();frames=[frame.reindex(clock).ffill() for frame in frames]
    if any(frame.equity.isna().any() for frame in frames):raise ValueError('Future sleeve equity filling forbidden')
    columns=frames[0].select_dtypes(include='number').columns
    combined=sum((frame[columns] for frame in frames)).reset_index()
    combined['gross_leverage']=combined.gross_exposure/combined.equity
    combined['net_leverage']=combined.net_exposure/combined.equity
    combined['margin_utilization']=combined.margin_used/combined.equity
    trades=pd.concat([pd.read_parquet(Path(row['path'])/'trades.parquet') for row in rows],ignore_index=True)
    fills=pd.concat([pd.read_parquet(Path(row['path'])/'fills.parquet') for row in rows],ignore_index=True)
    score=metrics(combined,trades,fills)
    reserve=sum(row.get('metrics',{}).get('indicative_exit_reserve_total',0) for row in rows)
    score['indicative_exit_reserve_total']=reserve
    score['return_after_indicative_exit_reserve']=(score['final_equity']-reserve)/score['initial_equity']-1
    score['liquidation_event_count']=sum(row.get('metrics',{}).get('liquidation_event_count',0) for row in rows)
    return combined,score


def anchored_months(frame,start=EVALUATION_START):
    equity=frame.set_index('timestamp').equity
    boundaries=[start+pd.DateOffset(months=k) for k in range(4)]
    values=[float(equity.asof(t)) for t in boundaries]
    return [values[k+1]/values[k]-1 for k in range(3)]


def bootstrap(frame):
    adjusted=frame.copy();adjusted['timestamp']=pd.to_datetime(adjusted.timestamp,utc=True).dt.as_unit('ns')
    end=adjusted.timestamp.max()
    if end==end.normalize():adjusted.loc[adjusted.timestamp==end,'timestamp']=end-pd.Timedelta(microseconds=1)
    x=daily_returns(adjusted).dropna().to_numpy();n=len(x)
    if n<7:return {}
    rng=np.random.default_rng(42);starts=rng.integers(0,n,(10000,int(np.ceil(n/7))))
    indices=((starts[:,:,None]+np.arange(7))%n).reshape(10000,-1)[:,:n]
    totals=np.expm1(np.log1p(x[indices]).sum(axis=1))
    return {'method':'conditional circular7dayblockbootstrap;10000draws;seed42;exploratory reused evaluation',
            'return_interval95':np.quantile(totals,[.025,.975]).tolist(),
            'return_interval_bonferroni19policies':np.quantile(totals,[.05/38,1-.05/38]).tolist()}


def choose_training(rows):
    chosen={};trials=[]
    for family in FAMILIES:
        scores=[]
        for scale in SCALES:
            group=[r for r in rows if r['family']==family and r['scale']==scale and r['phase']=='training' and not r['stress']]
            _,score=aggregate(group);trials.append({'family':family,'scale':scale,**score})
            rank=score.get('sharpe') if score.get('sharpe') is not None else -np.inf
            scores.append((rank,-abs(scale-1),scale))
        chosen[family]=max(scores)[2]
    return {'chosen':chosen,'training_trials':trials,'selection_basis':'training only; one common duration scale for all8sleeves'}


def summarize(rows,selection,out,protocol):
    root=Path(out);summaries=[]
    for family,scale in selection['chosen'].items():
        def group(phase,neighbor=scale,stress=False):return [r for r in rows if r['family']==family and r['scale']==neighbor and r['phase']==phase and r['stress']==stress]
        validations=[aggregate(group(f'validation{k}'))[1] for k in [1,2,3]]
        validation_return=float(np.prod([1+x['total_return'] for x in validations])-1)
        hold_rows=group('holdout');frame,score=aggregate(hold_rows)
        stressed,stress=aggregate(group('holdout',stress=True));months=anchored_months(frame)
        neighbors={str(s):aggregate(group('holdout',s))[1]['total_return'] for s in SCALES}
        reserved_neighbors={str(s):aggregate(group('holdout',s))[1]['return_after_indicative_exit_reserve'] for s in SCALES}
        positive=sum(row['metrics']['total_return']>0 for row in hold_rows)
        traded=sum((row['metrics'].get('fill_count') or 0)>0 for row in hold_rows)
        validation_reserved=float(np.prod([1+x['return_after_indicative_exit_reserve'] for x in validations])-1)
        risk_rows=sum((group('holdout',neighbor) for neighbor in SCALES),[])+group('holdout',stress=True)+sum((group(f'validation{k}') for k in [1,2,3]),[])
        liquidations=sum(row['metrics']['liquidation_event_count'] for row in risk_rows)
        checks={'validation_positive':validation_return>0,'evaluation_positive':score['total_return']>0,
            'jointstress_positive':stress['total_return']>0,'two_positive_months':sum(x>0 for x in months)>=2,
            'sharpe_at_least_half':score.get('sharpe') is not None and score['sharpe']>=.5,'minute_drawdown_within20pct':score['max_drawdown']<=.2,
            'all_neighbors_positive':all(x>0 for x in neighbors.values()),'no_liquidations':liquidations==0,
            'validation_positive_after_indicative_reserve':validation_reserved>0,'evaluation_positive_after_indicative_reserve':score['return_after_indicative_exit_reserve']>0,
            'jointstress_positive_after_indicative_reserve':stress['return_after_indicative_exit_reserve']>0,
            'all_neighbors_positive_after_indicative_reserve':all(x>0 for x in reserved_neighbors.values())}
        if family=='cross_sectional_momentum':checks['basket_traded_at_least_four_assets']=traded>=4
        else:checks['broad_symbol_success']=positive>=5
        summaries.append({'family':family,'chosen_scale':scale,'parameters':parameters(family,scale),
            'validation_fold_metrics':validations,'validation_compounded_return':validation_return,'validation_return_after_indicative_reserve':validation_reserved,
            'holdout':score,'stress':stress,'anchored_month_returns':months,'neighbor_evaluation_returns':neighbors,
            'neighbor_returns_after_indicative_reserve':reserved_neighbors,'later_trial_liquidation_events':liquidations,
            'positive_symbols':positive,'traded_symbols':traded,'symbols':{row['symbol']:row['metrics'] for row in hold_rows},'bootstrap':bootstrap(frame),
            'checks':checks,'historical_hurdles_passed':all(checks.values()),'research_status':'exploratory reused evaluation; not untouched'})
        destination=root/'pooled'/family;destination.mkdir(parents=True,exist_ok=True)
        frame.to_parquet(destination/'equity.parquet',index=False);stressed.to_parquet(destination/'stress_equity.parquet',index=False)
    result={'protocol':protocol,'families':summaries,'pass_count':sum(row['historical_hurdles_passed'] for row in summaries),
            'research_status':'exploratory reused historical evaluation; original13policyresults remain separate and unchanged'}
    dump(root/'summary.json',result);dump(root/'all_trials.json',rows);return result


def report(out,publish='docs/minute_directional_results'):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    root=Path(out);destination=Path(publish);destination.mkdir(parents=True,exist_ok=True)
    summary=json.loads((root/'summary.json').read_text())
    for name in ['protocol.json','selection.json','summary.json','all_trials.json','source_lock.json']:
        dump(destination/name,json.loads((root/name).read_text()))
    for name in ['executed_run.py','executed_signals.py']:(destination/name).write_bytes((root/name).read_bytes())
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.09,
                    subplot_titles=['Exploratory evaluation · pooled $100,000 equity','Drawdown · hourly display, full minute/funding-event metrics'])
    tables=[];equities=[];provenance=[];ledgers={name:[] for name in ['trades','funding','fills','positions']}
    for family in summary['families']:
        name=family['family'];scale=family['chosen_scale']
        frame=pd.read_parquet(root/'pooled'/name/'equity.parquet').set_index('timestamp')
        hourly=frame[['equity','funding_pnl','trading_fees','realized_pnl','unrealized_pnl','gross_exposure']].resample('1h').last()
        drawdown=frame.equity/frame.equity.cummax()-1
        fig.add_trace(go.Scatter(x=hourly.index,y=hourly.equity,name=name),row=1,col=1)
        fig.add_trace(go.Scatter(x=hourly.index,y=drawdown.resample('1h').min()*100,name=name,showlegend=False),row=2,col=1)
        hourly=hourly.reset_index();hourly['family']=name;equities.append(hourly)
        tables.append({'family':name,'chosen_scale':scale,'validation':family['validation_compounded_return'],
            'evaluation':family['holdout']['total_return'],'stress':family['stress']['total_return'],'sharpe':family['holdout']['sharpe'],
            'drawdown':family['holdout']['max_drawdown'],'positive_assets':family['positive_symbols'],'funding':family['holdout']['funding_pnl'],
            'fees':family['holdout']['trading_fees'],'liquidations':family['holdout']['liquidation_event_count'],
            'exit_reserve':family['holdout']['indicative_exit_reserve_total'],'reserve_return':family['holdout']['return_after_indicative_exit_reserve'],
            'passed':family['historical_hurdles_passed']})
        for scenario in ['base','stress']:
            for symbol in SYMBOLS:
                source=root/'holdout'/name/f'{scale:g}'/scenario/symbol
                metadata=json.loads((source/'metadata.json').read_text())
                provenance.append({'family':name,'scale':scale,'symbol':symbol,'scenario':scenario,
                    'fingerprints':metadata['parameters']['fingerprints'],'source_manifest':metadata['source_manifest'],
                    'terminal_open_positions':metadata['parameters']['terminal_open_position_count'],
                    'indicative_exit_reserve':metadata['parameters']['indicative_exit_reserve']})
                for ledger,collection in ledgers.items():
                    frame=pd.read_parquet(source/f'{ledger}.parquet')
                    if frame.empty:continue
                    frame['family']=name;frame['chosen_scale']=scale;frame['underlying_symbol']=symbol;frame['scenario']=scenario
                    collection.append(frame)
    comparison=pd.DataFrame(tables);comparison.to_csv(destination/'comparison.csv',index=False)
    pd.concat(equities,ignore_index=True).to_csv(destination/'equity_hourly.csv',index=False)
    for ledger,collection in ledgers.items():
        if collection:pd.concat(collection,ignore_index=True).to_csv(destination/f'{ledger}_ledger.csv',index=False)
    dump(destination/'source_provenance.json',provenance)
    fig.add_hline(y=100000,line_dash='dot',line_color='#64748b',row=1,col=1)
    fig.update_layout(template='plotly_dark',height=720,paper_bgcolor='#0b1220',plot_bgcolor='#102033',legend=dict(orientation='h',y=-.13),margin=dict(t=65,b=90))
    fig.update_yaxes(title_text='USD',row=1,col=1);fig.update_yaxes(title_text='%',row=2,col=1)
    display=comparison.copy()
    for col in ['validation','evaluation','stress','drawdown','reserve_return']:display[col]=display[col].map(lambda v:f'{v:.3%}')
    display['sharpe']=display.sharpe.map(lambda v:'undefined' if pd.isna(v) else f'{v:.2f}')
    for col in ['funding','fees','exit_reserve']:display[col]=display[col].map(lambda v:f'${v:,.2f}')
    display['passed']=display.passed.map({True:'PASS',False:'FAIL'})
    residual=sum(x['terminal_open_positions']>0 for x in provenance)
    body=fig.to_html(full_html=False,include_plotlyjs=True)
    page=f'''<!doctype html><html><head><meta charset="utf-8"><title>Aster · Exploratory Directional Perpetuals</title>
<style>body{{background:#0b1220;color:#dbe7f7;font:15px system-ui;max-width:1480px;margin:40px auto;padding:0 28px}}h1{{font-size:34px}}p{{line-height:1.6;color:#b9c9dc}}.panel{{background:#102033;padding:24px;border-radius:16px;margin:24px 0}}.label{{color:#6ee7cf;text-transform:uppercase;letter-spacing:2px}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:11px;border-bottom:1px solid #29415b;text-align:right}}td:first-child,th:first-child{{text-align:left}}a{{color:#6ee7cf}}</style></head><body>
<div class="label">Aster · Exploratory Research Extension</div><h1>Signed perpetual hypotheses on a reused historical year</h1>
<div class="panel"><strong>{summary['pass_count']} / 6 hypotheses passed the declared exploratory historical hurdles.</strong><p>The same historical evaluation period was previously examined in thirteen other policies. This new batch is exploratory and cannot establish untouched-holdout or non-overfit proof. All six hypotheses, all duration scales and all failures are retained. Trend variants overlap economically. The daily ranked long/short basket is a distinct portfolio hypothesis: the two highest ranks long, the two lowest short, and the middle four in cash. Initial active-leg entry notionals balance; subsequent notional drift and beta are not neutralized.</p></div>
<p>Actual Binance one-minute perpetual trades, mark prices and funding cover 5 October 2025–5 October 2026. The first six months select one common duration scale per hypothesis. Validation uses three fresh-wallet monthly folds; the reused final evaluation covers 5 July–5 October 2026. Nineteen cumulative policy and hypothesis comparisons are disclosed with conservative conditional bootstrap adjustment. The five scalar hypotheses require at least five profitable asset sleeves. The ranked basket instead requires actual fills in at least four assets, while retaining every losing hedge leg in portfolio P&L.</p>
<div class="panel" style="overflow:auto">{display.to_html(index=False,border=0)}</div>{body}
<div class="panel"><h2>Accounting and execution assumptions</h2><p>Eight independent $12,500 sleeves total $100,000. Native linear perpetual long/short quantities use 25% of sleeve equity as entry notional at each direction change and remain fixed between changes. Isolated leverage is one. Actual settled funding is a separate cash flow, including cutoff settlements supplied by the source. 1000PEPE retains its native bundle units and prices. The base taker fee is 5 bps; slippage is 2, 5 or 8 bps by liquidity class. Joint stress doubles fees and slippage, adds one minute delay and halves participation. {residual} chosen evaluation and stress sleeves end with actual marked open positions; no terminal orders or artificial closes are generated. Indicative exit reserve subtracts the assumed final-position fee and adverse slippage only as a diagnostic. It is not an executable fill, volume guarantee, trading cash flow or future liquidation forecast. Positive reserve-adjusted diagnostic returns and zero risk liquidations are additional hurdles.</p><p>Minute marks cannot observe intraminute liquidation. Current symbol rules approximate historical ones. The fixed surviving universe is not survivorship-free; same-venue archives are not independent market validation. Charts display hourly samples; final evaluation risk metrics use minute and funding-clock equity. Original thirteen-policy outcomes remain separate and unchanged.</p><p><a href="summary.json">Every hurdle and asset result</a> · <a href="all_trials.json">All 480 trials</a> · <a href="trades_ledger.csv">Trade ledger</a> · <a href="funding_ledger.csv">Funding ledger</a> · <a href="source_provenance.json">Source fingerprints</a> · <a href="protocol.json">Frozen protocol</a></p></div></body></html>'''
    (destination/'report.html').write_text(page);return destination/'report.html'


def execute_jobs(pool,jobs,rows,root):
    for row in pool.map(job,jobs):
        rows.append(row);print(row['phase'],row['family'],row['scale'],row['symbol'],'stress' if row['stress'] else 'base',flush=True)
    dump(Path(root)/'all_trials_progress.json',rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',default='data_cache/minute-perpetual-1y');parser.add_argument('--out',default='results/minute-directional-1y-v2')
    parser.add_argument('--workers',type=int,default=4);parser.add_argument('--publish',default='docs/minute_directional_results')
    parser.add_argument('--freeze-only',action='store_true');parser.add_argument('--training-only',action='store_true');parser.add_argument('--report-only',action='store_true')
    args=parser.parse_args();protocol=freeze(args.out);root=Path(args.out)
    if args.freeze_only:print('Exploratory hypotheses and sources frozen before any numeric outcomes.');return
    if args.report_only:print(report(args.out,args.publish));return
    rows=[]
    if 'cross_sectional_momentum' in FAMILIES:
        for scale in SCALES:cross_features(args.cache,args.out,TRAIN_END,scale)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs=[(family,symbol,scale,'training',str(START),str(TRAIN_END),False,args.cache,args.out) for family in FAMILIES for scale in SCALES for symbol in SYMBOLS]
        execute_jobs(pool,jobs,rows,root)
        selection=choose_training(rows);selected=root/'selection.json'
        if selected.exists() and json.loads(selected.read_text())!=json_safe(selection):raise RuntimeError('Training selection changed')
        dump(selected,selection)
        if args.training_only:print('Training selection saved; later evaluation jobs not dispatched.');return
        # The common training-only selection is durable before any later jobs dispatch.
        jobs=[]
        for family,scale in selection['chosen'].items():
            for k in range(3):
                begin=TRAIN_END+pd.DateOffset(months=k);stop=TRAIN_END+pd.DateOffset(months=k+1)
                if family=='cross_sectional_momentum':cross_features(args.cache,args.out,stop,scale)
                jobs.extend((family,symbol,scale,f'validation{k+1}',str(begin),str(stop),False,args.cache,args.out) for symbol in SYMBOLS)
            for neighbor in SCALES:
                if family=='cross_sectional_momentum':cross_features(args.cache,args.out,END,neighbor)
                jobs.extend((family,symbol,neighbor,'holdout',str(EVALUATION_START),str(END),False,args.cache,args.out) for symbol in SYMBOLS)
            jobs.extend((family,symbol,scale,'holdout',str(EVALUATION_START),str(END),True,args.cache,args.out) for symbol in SYMBOLS)
        execute_jobs(pool,jobs,rows,root)
    summarize(rows,selection,args.out,protocol);print(report(args.out,args.publish))


if __name__=='__main__':main()
