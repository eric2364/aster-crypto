"""Five fixed policies of ONE funding-carry family; audited paired spot/perpetual engine.

Freeze before inspecting any outcomes:
python examples/minute_carry/run.py --freeze-only
python examples/minute_carry/run.py --phase validation --workers 2
python examples/minute_carry/run.py --phase holdout --workers 2
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from fractions import Fraction
import hashlib
import json
import math
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

START=pd.Timestamp('2025-10-05',tz='UTC')
TRAIN_END=pd.Timestamp('2026-04-05',tz='UTC')
HOLDOUT_START=pd.Timestamp('2026-07-05',tz='UTC')
END=pd.Timestamp('2026-10-05',tz='UTC')
SYMBOLS=['BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT']
POLICIES={
 'always_hedged':'Long spot/short matching perpetual base units continuously; negative funding is paid.',
 'positive_trailing':'Enter while the trailing three published settlement rates have positive mean; otherwise flat.',
 'funding_rotation':'Hold the top two positive trailing-three-rate assets ranked across the fixed eight-asset universe; idle sleeve cash remains idle.',
 'funding_hysteresis':'Enter after a positive latest published rate; exit after three consecutive nonpositive rates; never short unlevered spot.',
 'risk_controlled':'Positive trailing-three mean plus previous 24h realized volatility below10%, absolute observed spot/perp basis below1%, and isolated risk ratio exit at50%.',
}


def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(json_safe(value),indent=2,allow_nan=False)+'\n')


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(out):
    protocol={'economic_families':1,'candidate_policies':POLICIES,'selection':'five fixed defaults; no parameter search or numerical training selection',
      'start':str(START),'training_end':str(TRAIN_END),'holdout_start':str(HOLDOUT_START),'end_exclusive':str(END),
      'symbols':SYMBOLS,'initial_pooled_capital':100000,'segregated_sleeve_capital':12500,
      'allocation_each_leg':.3,'perpetual_leverage':2,'margin_mode':'isolated','max_gross_leverage':1,
      'decision_clock':'00:01UTC daily plus first completed minute in each fresh-wallet phase',
      'funding_predictor':'only already settled rates, published settlement timestamp+1minute; three observations required for trailing means',
      'quantity':'fixed entry units until exit; explicit1000spotPEPE per1unit1000PEPE perpetual; common lot-size grid',
      'base_fees_bps':{'spot':10,'perpetual':5},'slippage_bps':{'BTCUSDT':2,'ETHUSDT':2,'DOGEUSDT':8,'PEPEUSDT':8,'other':5},
      'participation':.05,'stress':'double all fees and slippage, one additional minute delay, half volume participation',
      'terminal':'predeclared close orders2minutes before end; partial residuals disclosed, not fabricated fills',
      'execution_validity_gate':'all base/stress sleeve terminal positions fully closed; otherwise historical hurdle pass is prohibited',
      'pair_risk':'flatten on >1% matched-base-unit imbalance persisting5minutes, or either leg liquidation; risk policy additionally exits maintenance+close-reserve/local-equity>=.5',
      'criteria':'validation return>0; holdout>0; jointstress>0; at least2of3positive anchored holdout months; Sharpe>=.5; minute maxdrawdown<=.2; >=5of8positive symbols',
      'multiple_testing':'five correlated variants of one carry family plus eight price/factor policies; conservative13-policy Bonferroni bootstrap tails',
      'limitations':['current fee/lot/risk metadata approximates historical rules','surviving fixed universe','minute marks miss intraminute liquidation','legs fill independently with volume/latency, no atomic exchange hedge','historical hurdle pass is not prospective edge proof']}
    destination=Path(out)/'protocol.json'
    if destination.exists() and json.loads(destination.read_text())!=json_safe(protocol):
        raise RuntimeError('Frozen policy protocol changed; use a new output directory and disclose another trial')
    if not destination.exists():dump(destination,protocol)
    lock=Path(out)/'policy_lock.json'
    value={'runner_sha256':fingerprint(__file__),'protocol_sha256':fingerprint(destination),'selection':'none; fixed before numerical outcomes'}
    if lock.exists():
        prior=json.loads(lock.read_text())
        if prior['protocol_sha256']!=value['protocol_sha256']:raise RuntimeError('Economic policy protocol changed')
        if prior['runner_sha256']!=value['runner_sha256']:
            if any(Path(out).rglob('metrics.json')):raise RuntimeError('Runner changed after numerical outcomes; fresh output/disclosed trial required')
            value['earlier_pre_outcome_implementation_hashes']=prior.get('earlier_pre_outcome_implementation_hashes',[])+[prior['runner_sha256']]
            dump(lock,value)
    else:dump(lock,value)
    return protocol


def common_step(spot_lot,perp_lot,base_units):
    a,b=Fraction(str(spot_lot)),Fraction(str(perp_lot))*int(base_units)
    denominator=math.lcm(a.denominator,b.denominator)
    return float(Fraction(math.lcm(a.numerator*(denominator//a.denominator),b.numerator*(denominator//b.denominator)),denominator))


def published_factors(funding,clock):
    """Backward as-of is invariant to appending or mutating future settlements."""
    frame=funding.sort_values('timestamp').copy()
    frame['available_at']=pd.to_datetime(frame.timestamp,utc=True)+pd.Timedelta(minutes=1)
    frame['trailing_mean']=frame.funding_rate.rolling(3,min_periods=3).mean()
    frame['three_nonpositive']=frame.funding_rate.le(0).rolling(3,min_periods=3).sum().eq(3)
    left=pd.DataFrame({'available_at':pd.DatetimeIndex(clock)})
    return pd.merge_asof(left,frame[['available_at','funding_rate','trailing_mean','three_nonpositive']],
                         on='available_at',direction='backward').set_index('available_at')


def decisions(spot,perp,funding,policy,begin,stop,units,rotation=None):
    completed=pd.DatetimeIndex(spot.timestamp+pd.Timedelta(minutes=1))
    decision_clock=completed[(completed.hour==0)&(completed.minute==1)]
    first=begin+pd.Timedelta(minutes=1)
    decision_clock=decision_clock.union(pd.DatetimeIndex([first]))
    decision_clock=decision_clock[(decision_clock>=begin)&(decision_clock<stop)]
    observed=published_factors(funding,decision_clock)
    if policy=='always_hedged':values=np.ones(len(decision_clock),dtype=int)
    elif policy=='positive_trailing':values=observed.trailing_mean.gt(0).astype(int).to_numpy()
    elif policy=='funding_rotation':values=rotation.reindex(decision_clock).fillna(False).astype(int).to_numpy()
    elif policy=='funding_hysteresis':
        active=False;values=[]
        for row in observed.itertuples():
            if row.funding_rate>0:active=True
            if row.three_nonpositive is True or row.three_nonpositive==True:active=False
            values.append(int(active))
    else:
        aligned=spot[['timestamp','close']].merge(perp[['timestamp','close']],on='timestamp',suffixes=('_spot','_perp'),validate='one_to_one')
        aligned['available_at']=aligned.timestamp+pd.Timedelta(minutes=1)
        aligned['volatility']=aligned.close_spot.pct_change().rolling(1440,min_periods=1440).std()*np.sqrt(1440)
        aligned['basis']=aligned.close_perp/(aligned.close_spot*units)-1
        risk=pd.merge_asof(pd.DataFrame({'available_at':decision_clock}),aligned[['available_at','volatility','basis']],on='available_at',direction='backward')
        values=(observed.trailing_mean.gt(0).to_numpy() & risk.volatility.lt(.10).to_numpy() & risk.basis.abs().lt(.01).to_numpy()).astype(int)
    return pd.Series(values,index=decision_clock,dtype=int)


class MatchedCarry(BaseStrategy):
    version='fixed-funding-carry-1'
    def __init__(self,spot_id,perp_id,units,signals,capital,stop,risk_controlled=False):
        self.spot_id=spot_id;self.perp_id=perp_id;self.units=units;self.signals=signals.to_dict()
        self.budget=capital*.3;self.stop=stop;self.risk_controlled=risk_controlled
        self.state=0;self.entry_at=None;self.planned_base=0;self.safety_exits=[];self.terminal_submitted=False;self.closing=False
    def flatten(self,ctx,reason):
        if self.closing:return
        ctx.target(self.spot_id,0);ctx.target(self.perp_id,0)
        if self.state:self.safety_exits.append({'timestamp':str(ctx.now),'reason':reason})
        self.state=0;self.entry_at=None;self.planned_base=0;self.closing=True
    def on_bars(self,ctx,bars):
        current={b['instrument_id']:b for b in bars}
        if self.spot_id not in current or self.perp_id not in current:return
        spot,perp=ctx.positions[self.spot_id],ctx.positions[self.perp_id]
        if ctx.now>=self.stop-pd.Timedelta(minutes=2):
            if not self.terminal_submitted:
                self.flatten(ctx,'predeclared_terminal_close');self.terminal_submitted=True
            return
        if self.closing:
            if abs(spot.quantity)>1e-8 or abs(perp.quantity)>1e-8:return
            self.closing=False
        if self.state and ctx.now>=self.entry_at+pd.Timedelta(minutes=5):
            mismatch=abs(spot.quantity+perp.quantity*self.units)
            if mismatch>max(self.planned_base*.01,1e-8):
                self.flatten(ctx,'leg_imbalance_or_liquidation');return
        if self.state and self.risk_controlled and abs(perp.quantity)>0:
            spec=ctx.instruments[self.perp_id];mark=ctx.portfolio.marks[self.perp_id]
            local=perp.collateral+ctx.portfolio.unrealized(self.perp_id)
            required=abs(perp.quantity)*mark*(spec.maintenance_rate+(spec.taker_bps+spec.liquidation_bps)/10000)
            if local<=0 or required/local>=.5:
                self.flatten(ctx,'isolated_risk_gate');return
        desired=self.signals.get(ctx.now)
        if desired is None or desired==self.state:return
        if not desired:self.flatten(ctx,'funding_policy_exit');return
        spot_spec,perp_spec=ctx.instruments[self.spot_id],ctx.instruments[self.perp_id]
        step=common_step(spot_spec.lot_size,perp_spec.lot_size,self.units)
        base=floor_step(self.budget/current[self.spot_id]['close'],step)
        derivative=base/self.units
        if base<spot_spec.min_quantity or derivative<perp_spec.min_quantity:return
        if base*current[self.spot_id]['close']<spot_spec.min_notional or derivative*current[self.perp_id]['close']<perp_spec.min_notional:return
        ctx.target(self.spot_id,base);ctx.target(self.perp_id,-derivative)
        self.state=1;self.entry_at=ctx.now;self.planned_base=base


def rotation_signals(spot_root,perp_root,begin,stop):
    clock=pd.date_range(START+pd.Timedelta(minutes=1),stop-pd.Timedelta(minutes=1),freq='1D',tz='UTC')
    clock=clock.union(pd.DatetimeIndex([begin+pd.Timedelta(minutes=1)]))
    columns={}
    for symbol in SYMBOLS:
        funding=pd.read_parquet(Path(perp_root)/symbol/'funding.parquet')
        funding=funding[funding.timestamp<stop]
        columns[symbol]=published_factors(funding,clock).trailing_mean
    scores=pd.DataFrame(columns,index=clock)
    # Stable alphabetical tie break; fixed top-two sleeves, no capital transfer.
    ranks=scores.rank(axis=1,method='first',ascending=False)
    return ranks.le(2)&scores.gt(0)


def run_job(args):
    policy,symbol,phase,stress,spot_root,perp_root,out,rotation=args
    begin,stop={'training':(START,TRAIN_END),'validation':(TRAIN_END,HOLDOUT_START),'holdout':(HOLDOUT_START,END)}[phase]
    destination=Path(out)/phase/policy/('stress' if stress else 'base')/symbol
    sources=[Path(spot_root)/symbol/'bars.parquet',Path(perp_root)/symbol/'bars.parquet',Path(perp_root)/symbol/'funding.parquet',Path(spot_root)/'instruments.json',Path(perp_root)/'instruments.json',Path(perp_root)/'cross_mapping.json']
    hashes={str(p):fingerprint(p) for p in sources}
    hashes['runner']=fingerprint(__file__)
    hashes['package']={str(p):fingerprint(p) for p in sorted(Path('aster').rglob('*.py'))}
    if (destination/'metrics.json').exists():
        stored=json.loads((destination/'metadata.json').read_text())['parameters']
        if stored['fingerprints']!=hashes:raise RuntimeError('Cached carry result source changed')
        return dict(policy=policy,symbol=symbol,phase=phase,stress=stress,path=str(destination),metrics=json.loads((destination/'metrics.json').read_text()))
    mapping=next(x for x in json.loads((Path(perp_root)/'cross_mapping.json').read_text())['mapping'] if x['spot_symbol']==symbol)
    units=mapping['spot_base_units_per_perpetual_quantity_unit']
    spot_spec=Instrument(**next(x for x in json.loads((Path(spot_root)/'instruments.json').read_text()) if x['symbol']==symbol))
    perp_spec=Instrument(**next(x for x in json.loads((Path(perp_root)/'instruments.json').read_text()) if x['id']==mapping['perpetual_instrument_id']))
    spot_spec=replace(spot_spec,maker_bps=20 if stress else 10,taker_bps=20 if stress else 10)
    perp_spec=replace(perp_spec,maker_bps=10 if stress else 5,taker_bps=10 if stress else 5)
    spot=pd.read_parquet(sources[0]);spot=spot[spot.timestamp<stop].copy()
    perp=pd.read_parquet(sources[1]);perp=perp[perp.timestamp<stop].copy()
    funding=pd.read_parquet(sources[2]);funding=funding[funding.timestamp<=stop].copy()
    if set(spot.timestamp)!=set(perp.timestamp):raise ValueError('Paired candles have unequal timestamp coverage; no silent intersection/forward-fill')
    if set(perp.instrument_id)!={perp_spec.id}:raise ValueError('Perpetual identity/unit mismatch')
    if set(funding.instrument_id)!={perp_spec.id}:raise ValueError('Funding must use original perpetual quantity units and identity')
    signals=decisions(spot,perp,funding,policy,begin,stop,units,rotation[symbol] if rotation is not None else None)
    spot=spot[spot.timestamp>=begin].copy();perp=perp[perp.timestamp>=begin].copy()
    # Spot inventory marks use actual spot observations, not a fabricated perpetual feed.
    spot['mark_open']=spot['open'];spot['mark_price']=spot['close']
    funding=funding[funding.timestamp>=begin].copy()
    bars=pd.concat([spot,perp],ignore_index=True).sort_values(['timestamp','instrument_id'])
    slip=2 if symbol in ['BTCUSDT','ETHUSDT'] else 8 if symbol in ['DOGEUSDT','PEPEUSDT'] else 5
    config=SimulationConfig(initial_balances={'binance':12500},leverage=2,margin_mode='isolated',max_gross_leverage=1,
        max_position_pct=.5,slippage_bps=slip*(2 if stress else 1),participation=.025 if stress else .05,
        execution_delay_bars=1 if stress else 0,record_every=1 if phase=='holdout' else 60)
    strategy=MatchedCarry(spot_spec.id,perp_spec.id,units,signals,12500,stop,policy=='risk_controlled')
    result=Engine([spot_spec,perp_spec],config).run(bars,strategy,funding=funding)
    verify_ledgers(result)
    source_manifest={'spot':json.loads((Path(spot_root)/symbol/'source_manifest.json').read_text()),
                     'perpetual':json.loads((Path(perp_root)/symbol/'source_manifest.json').read_text()),'mapping':mapping}
    _,score=export_result(result,destination,parameters={'policy':policy,'family':'funding_carry','economic_families':1,
        'phase':phase,'stress':stress,'fingerprints':hashes,'safety_exits':strategy.safety_exits,'initial_capital':12500,
        'fixed_entry_each_leg_budget':3750,'requested_start':str(begin),'requested_end_exclusive':str(stop),
        'publication_delay_minutes':1,'source_base_units_per_perpetual_quantity':units,
        'equity_sampling_minutes':1 if phase=='holdout' else 60,'terminal_residual_position_count':len(result.positions)},
        data_source='Actual Binance checksum-verified separate spot/perpetual minute trade bars, mark bars and settled funding',source_manifest=source_manifest)
    return dict(policy=policy,symbol=symbol,phase=phase,stress=stress,path=str(destination),metrics=score)


def aggregate(rows):
    frames=[pd.read_parquet(Path(r['path'])/'equity.parquet').set_index('timestamp') for r in rows]
    clock=frames[0].index
    for frame in frames[1:]:clock=clock.union(frame.index)
    clock=clock.sort_values()
    frames=[f.reindex(clock).ffill() for f in frames]
    if any(f.equity.isna().any() for f in frames):raise ValueError('No prior sleeve equity at pooled timestamp; future-fill forbidden')
    columns=frames[0].select_dtypes(include='number').columns
    frame=sum((f[columns] for f in frames)).reset_index()
    frame['gross_leverage']=frame.gross_exposure/frame.equity;frame['net_leverage']=frame.net_exposure/frame.equity
    frame['margin_utilization']=frame.margin_used/frame.equity
    trades=pd.concat([pd.read_parquet(Path(r['path'])/'trades.parquet') for r in rows],ignore_index=True)
    fills=pd.concat([pd.read_parquet(Path(r['path'])/'fills.parquet') for r in rows],ignore_index=True)
    return frame,metrics(frame,trades,fills)


def interval(frame):
    adjusted=frame.copy()
    # Actual Parquet files preserve millisecond units; allow the endpoint microsecond.
    adjusted['timestamp']=pd.to_datetime(adjusted.timestamp,utc=True).dt.as_unit('ns')
    end=adjusted.timestamp.max()
    if end==end.normalize():adjusted.loc[adjusted.timestamp==end,'timestamp']=end-pd.Timedelta(microseconds=1)
    x=daily_returns(adjusted).dropna().to_numpy();n=len(x)
    if n<7:return {}
    rng=np.random.default_rng(42);starts=rng.integers(0,n,(10000,int(np.ceil(n/7))))
    indices=((starts[:,:,None]+np.arange(7))%n).reshape(10000,-1)[:,:n]
    totals=np.expm1(np.log1p(x[indices]).sum(axis=1))
    return {'method':'circular7dayblockbootstrap;10000draws;seed42;conditional observed holdout',
            'return_interval95':np.quantile(totals,[.025,.975]).tolist(),
            'return_interval_bonferroni13policies':np.quantile(totals,[.05/26,1-.05/26]).tolist()}


def summarize(out):
    root=Path(out);summaries=[]
    for policy in POLICIES:
        sets={}
        for phase,stress in [('validation',False),('holdout',False),('holdout',True)]:
            rows=[]
            for symbol in SYMBOLS:
                path=root/phase/policy/('stress' if stress else 'base')/symbol
                if not (path/'metrics.json').exists():return None
                rows.append(dict(symbol=symbol,path=str(path),metrics=json.loads((path/'metrics.json').read_text())))
            frame,score=aggregate(rows);sets[(phase,stress)]=(frame,score,rows)
        val=sets['validation',False][1];frame,hold,rows=sets['holdout',False];stress=sets['holdout',True][1]
        equity=frame.set_index('timestamp').equity
        boundaries=[HOLDOUT_START+pd.DateOffset(months=k) for k in range(4)]
        marks=[float(equity.asof(t)) for t in boundaries]
        months=[marks[k+1]/marks[k]-1 for k in range(3)]
        checks={'validation_positive':val['total_return']>0,'holdout_positive':hold['total_return']>0,
                'jointstress_positive':stress['total_return']>0,'two_positive_months':sum(v>0 for v in months)>=2,
                'sharpe_at_least_half':hold.get('sharpe') is not None and hold['sharpe']>=.5,
                'minute_drawdown_within20pct':hold['max_drawdown']<=.2,'broad_symbol_success':sum(r['metrics']['total_return']>0 for r in rows)>=5,
                'all_terminal_positions_closed':all(json.loads((Path(row['path'])/'metadata.json').read_text())['parameters']['terminal_residual_position_count']==0 for _,_,phase_rows in sets.values() for row in phase_rows)}
        summaries.append(dict(policy=policy,economic_family='funding_carry',validation=val,holdout=hold,
            stress=stress,anchored_month_returns=months,symbols={r['symbol']:r['metrics'] for r in rows},
            bootstrap=interval(frame),checks=checks,historical_hurdles_passed=all(checks.values())))
        path=root/'pooled'/policy;path.mkdir(parents=True,exist_ok=True);frame.to_parquet(path/'equity.parquet',index=False)
    value={'economic_families':1,'fixed_policies':5,'policies':summaries,'policy_hurdle_pass_count':sum(x['historical_hurdles_passed'] for x in summaries),
           'independence_warning':'Five correlated funding-carry policies do not constitute five independent profitable strategy families.'}
    dump(root/'summary.json',value);return value


def report(out,destination='docs/minute_carry_results'):
    """Small review artifacts complement complete per-sleeve CSV/Parquet ledgers."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    root=Path(out);dest=Path(destination);dest.mkdir(parents=True,exist_ok=True)
    summary=json.loads((root/'summary.json').read_text())
    dump(dest/'summary.json',summary);dump(dest/'protocol.json',json.loads((root/'protocol.json').read_text()))
    dump(dest/'policy_lock.json',json.loads((root/'policy_lock.json').read_text()))
    if (root/'analysis_repair.json').exists():dump(dest/'analysis_repair.json',json.loads((root/'analysis_repair.json').read_text()))
    if (root/'execution_output_hashes.json').exists():dump(dest/'execution_output_hashes.json',json.loads((root/'execution_output_hashes.json').read_text()))
    if (root/'executed_runner.py').exists():(dest/'executed_runner.py').write_bytes((root/'executed_runner.py').read_bytes())
    hourly=[];trades=[];funding=[];positions=[];provenance=[]
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.09,
                      subplot_titles=['Pooled equity · $100,000 in eight segregated sleeves','Drawdown · displayed hourly, metrics use every minute'])
    for item in summary['policies']:
        policy=item['policy']
        frame=pd.read_parquet(root/'pooled'/policy/'equity.parquet').set_index('timestamp')
        drawdown=frame.equity/frame.equity.cummax()-1
        sampled=frame[['equity','funding_pnl','trading_fees','realized_pnl','unrealized_pnl','gross_exposure']].resample('1h').last()
        fig.add_trace(go.Scatter(x=sampled.index,y=sampled.equity,name=policy),row=1,col=1)
        fig.add_trace(go.Scatter(x=sampled.index,y=drawdown.resample('1h').min()*100,name=policy,showlegend=False),row=2,col=1)
        sampled=sampled.reset_index();sampled['policy']=policy;hourly.append(sampled)
        for phase,scenario in [('validation','base'),('holdout','base'),('holdout','stress')]:
            for symbol in SYMBOLS:
                path=root/phase/policy/scenario/symbol
                metadata=json.loads((path/'metadata.json').read_text())
                provenance.append({'policy':policy,'phase':phase,'scenario':scenario,'symbol':symbol,
                    'data_source':metadata['data_source'],'fingerprints':metadata['parameters']['fingerprints'],
                    'mapping':metadata['source_manifest']['mapping'],'terminal_residual_positions':metadata['parameters']['terminal_residual_position_count'],
                    'safety_exits':metadata['parameters']['safety_exits']})
                for name,collection in [('trades',trades),('funding',funding),('positions',positions)]:
                    ledger=pd.read_parquet(path/f'{name}.parquet')
                    if ledger.empty:continue
                    ledger['policy']=policy;ledger['phase']=phase;ledger['scenario']=scenario;ledger['spot_symbol']=symbol
                    collection.append(ledger)
    pd.concat(hourly,ignore_index=True).to_csv(dest/'equity_hourly.csv',index=False)
    for collection,name in [(trades,'trade_ledger'),(funding,'funding_ledger'),(positions,'terminal_positions')]:
        if collection:pd.concat(collection,ignore_index=True).to_csv(dest/f'{name}.csv',index=False)
    dump(dest/'source_provenance.json',provenance)
    fig.add_hline(y=100000,line_dash='dot',line_color='#64748b',row=1,col=1)
    fig.update_layout(template='plotly_dark',height=690,paper_bgcolor='#0b1220',plot_bgcolor='#0f1c2e',
                      legend=dict(orientation='h',y=-.12),margin=dict(l=65,r=35,t=75,b=75))
    fig.update_yaxes(title_text='USD',row=1,col=1);fig.update_yaxes(title_text='%',row=2,col=1)
    def pct(value):return '—' if value is None else f'{value*100:.3f}%'
    def ratio(value):return '—' if value is None else f'{value:.2f}'
    rows=''.join('<tr>'+''.join(f'<td>{value}</td>' for value in [item['policy'],
        pct(item['validation']['total_return']),pct(item['holdout']['total_return']),pct(item['stress']['total_return']),
        ratio(item['holdout'].get('sharpe')),pct(item['holdout']['max_drawdown']),
        sum(score['total_return']>0 for score in item['symbols'].values()),
        'Pass' if item['historical_hurdles_passed'] else 'Fail'])+'</tr>' for item in summary['policies'])
    chart=fig.to_html(full_html=False,include_plotlyjs=True)
    residual_cases=sum(row['terminal_residual_positions']>0 for row in provenance)
    page=f'''<!doctype html><html><head><meta charset="utf-8"><title>Funding Carry · Fixed Policies</title>
<style>body{{background:#0b1220;color:#d9e4f3;font:15px system-ui;margin:0;padding:40px;max-width:1400px;margin:auto}}h1{{font-size:34px}}.eyebrow{{color:#62d8c7;text-transform:uppercase;letter-spacing:2px}}.panel{{background:#102033;padding:24px;border-radius:15px;margin:22px 0}}table{{border-collapse:collapse;width:100%}}td,th{{padding:13px;text-align:left;border-bottom:1px solid #284057}}p{{line-height:1.6;color:#b4c4d9}}a{{color:#62d8c7}}</style></head><body>
<div class="eyebrow">Aster · Audited Minute Research</div><h1>One funding-carry family. Five fixed policies.</h1>
<p>Actual Binance spot and perpetual trade bars, mark prices and historical funding. Latest year: 5 October 2025–5 October 2026. Six months of earlier observations provide causal warmup; validation April–July precedes the untouched July–October holdout. Fixed policies were frozen before outcomes; no parameter search was used.</p>
<div class="panel"><strong>{summary['policy_hurdle_pass_count']} / 5 policies passed all declared historical hurdles.</strong><p>These correlated policies are one economic family. A historical pass does not establish a durable future edge. Capital is $100,000 across eight segregated $12,500 sleeves; each entry allocates 30% to spot and a matching 30% perpetual short, held in fixed base units. PEPE is explicitly paired with native 1000PEPE contract units.</p><p>{residual_cases} of120 completed sleeve runs retained terminal inventory because independently executed legs could not complete the declared close window under volume/order constraints. Equity includes those actual marked residuals, and the strict terminal-flat hurdle fails; no closure or cash was fabricated. Inspect the <a href="terminal_positions.csv">terminal-position ledger</a> before interpreting returns.</p></div>
<div class="panel"><table><thead><tr><th>Policy</th><th>Validation</th><th>Holdout</th><th>Joint stress</th><th>Sharpe</th><th>Max DD</th><th>Positive assets / 8</th><th>All hurdles</th></tr></thead><tbody>{rows}</tbody></table></div>
{chart}<div class="panel"><h2>Execution and funding are separate costs</h2><p>Base taker assumptions: spot 10 bps, perpetual 5 bps; slippage 2/5/8 bps by liquidity class. Joint stress doubles fees and slippage, adds one minute execution delay, and halves volume participation. Funding predictors use only settled rates with a one minute publication lag. Independent leg fills can create temporary hedge imbalance; safety and terminal residuals are disclosed. No future perpetual prices, settlement rates or fabricated terminal fills are used.</p><p>Current lot sizes/risk tiers approximate historical rules; minute marks cannot observe intraminute liquidations, and the fixed surviving universe is not survivorship-free. Charts show hourly samples; holdout drawdown and hurdle calculations use the full minute/funding-event equity ledger. Confidence intervals are conditional block bootstraps with conservative 13-policy multiplicity adjustment, not profitability guarantees.</p><p>Review artifacts: <a href="summary.json">metrics and all checks</a> · <a href="protocol.json">frozen protocol</a> · <a href="trade_ledger.csv">trade ledger</a> · <a href="funding_ledger.csv">funding ledger</a> · <a href="source_provenance.json">source identities and safety exits</a>.</p></div></body></html>'''
    (dest/'report.html').write_text(page)
    return dest/'report.html'


def analyze_existing(out,destination):
    """Mechanical summary recovery; execution fingerprints and ledgers stay immutable."""
    root=Path(out);lock=json.loads((root/'policy_lock.json').read_text())
    executed=root/'executed_runner.py'
    if not executed.exists() or fingerprint(executed)!=lock['runner_sha256']:
        raise RuntimeError('Verified frozen executed-runner snapshot required')
    if fingerprint(root/'protocol.json')!=lock['protocol_sha256']:raise RuntimeError('Frozen economic protocol changed')
    paths=sorted(root.glob('*/*/*/*/metadata.json'))
    if len(paths)!=120:raise RuntimeError(f'Need120 verified model results, got{len(paths)}')
    outputs=[]
    for path in paths:
        metadata=json.loads(path.read_text())
        if metadata['parameters']['fingerprints']['runner']!=lock['runner_sha256']:
            raise RuntimeError('Mixed executed runner fingerprints')
        outputs.append({'path':str(path.parent.relative_to(root)),
            'sha256':{name:fingerprint(path.parent/name) for name in ['metadata.json','metrics.json','equity.parquet','fills.parquet','trades.parquet','funding.parquet','events.parquet','positions.parquet']}})
    dump(root/'execution_output_hashes.json',outputs)
    dump(root/'analysis_repair.json',{'type':'postprocessing-only dtype repair after all120 simulations completed',
        'executed_runner_sha256':lock['runner_sha256'],'analysis_runner_sha256':fingerprint(__file__),
        'change':'cast copied equity timestamps to nanoseconds before subtracting1microsecond at terminal UTC midnight in conditional bootstrap',
        'unchanged':['five economic policies','parameters','orders','fills','fees','funding','portfolio equity','raw metrics','source/data/model fingerprints'],
        'models_rerun':0,'preliminary_execution':'old results/minute-carry-1y preserved8validation artifacts; interrupted for terminal-delay mechanical bug before anyholdout; no metrics inspected or policy retuning',
        'original_failure':'Pandas3 rejected microsecond endpoint assignment into actual datetime64[ms,UTC] Parquet timestamps'})
    if summarize(out) is None:raise RuntimeError('All result ledgers required')
    for row in outputs:
        for name,digest in row['sha256'].items():
            if fingerprint(root/row['path']/name)!=digest:raise RuntimeError('Execution artifact mutated during analysis')
    return report(out,destination)


def self_test():
    assert common_step(.1,1,1000)==1000
    t=pd.date_range('2025-10-05',periods=4,freq='8h',tz='UTC')
    history=pd.DataFrame({'timestamp':t,'funding_rate':[.001,.002,-.003,9]})
    clocks=pd.DatetimeIndex([t[2],t[2]+pd.Timedelta(minutes=1)])
    observed=published_factors(history,clocks)
    assert observed.iloc[0].funding_rate==.002
    assert observed.iloc[1].funding_rate==-.003
    changed=history.copy();changed.loc[3,'funding_rate']=-9
    pd.testing.assert_frame_equal(observed,published_factors(changed,clocks))
    print('Carry causal publication and1000PEPE lot-grid self-tests passed.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spot-cache',default='data_cache/minute-1y');parser.add_argument('--perp-cache',default='data_cache/minute-perpetual-1y')
    parser.add_argument('--out',default='results/minute-carry-1y-v2');parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--phase',choices=['training','validation','holdout','all'],default='validation')
    parser.add_argument('--policies',nargs='+',choices=list(POLICIES),default=list(POLICIES));parser.add_argument('--symbols',nargs='+',choices=SYMBOLS,default=SYMBOLS)
    parser.add_argument('--freeze-only',action='store_true');parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--report-only',action='store_true');parser.add_argument('--review-out',default='docs/minute_carry_results')
    parser.add_argument('--analysis-only',action='store_true',help='Recover summary from verified frozen executed models; never run simulations')
    args=parser.parse_args()
    if args.self_test:self_test();return
    if args.analysis_only:print(analyze_existing(args.out,args.review_out));return
    freeze(args.out)
    if args.freeze_only:print('Five fixed carry policies frozen; no numerical market outcomes read.');return
    if args.report_only:
        if summarize(args.out) is None:raise RuntimeError('All validation/holdout/stress results required before report')
        print(report(args.out,args.review_out));return
    phases=['training','validation','holdout'] if args.phase=='all' else [args.phase]
    jobs=[]
    for phase in phases:
        begin,stop={'training':(START,TRAIN_END),'validation':(TRAIN_END,HOLDOUT_START),'holdout':(HOLDOUT_START,END)}[phase]
        rotation=rotation_signals(args.spot_cache,args.perp_cache,begin,stop) if 'funding_rotation' in args.policies else None
        for policy in args.policies:
            for stress in ([False,True] if phase=='holdout' else [False]):
                for symbol in args.symbols:
                    jobs.append((policy,symbol,phase,stress,args.spot_cache,args.perp_cache,args.out,rotation if policy=='funding_rotation' else None))
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(run_job,jobs):
            print(row['phase'],row['policy'],row['symbol'],'stress' if row['stress'] else 'base',flush=True)
    summary=summarize(args.out)
    if summary is not None:
        print('Completed fixed carry report:',Path(args.out)/'summary.json');print(report(args.out,args.review_out))


if __name__=='__main__':main()
