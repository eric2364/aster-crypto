"""Independent no-trade residual cohort certificate. Never invokes Engine.

Reconstructs training statistics separately; all six failed admissions make
zero orders/positions the exact expected trajectory for this frozen cohort.
Unexpected eligibility/activity fails this auditor rather than being hidden.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
import sys
import subprocess
import tempfile
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audit.verify_external_outputs import close,sha
from examples.residual_convergence import run as runner

START=pd.Timestamp('2025-10-05',tz='UTC');BETA_END=pd.Timestamp('2026-01-05',tz='UTC')
TRAIN_END=pd.Timestamp('2026-04-05',tz='UTC');END=pd.Timestamp('2026-10-05',tz='UTC')
PREREG='ae9fbd4ca48fac2b56c9c3ad0bdffc76fbf8ea44'


def verify_source_anchor(lock):
    """Later documentation commits may replicate the exact preregistered code."""
    for path,expected in lock['sources'].items():
        original=subprocess.run(['git','show',f'{PREREG}:{path}'],capture_output=True,check=True).stdout
        assert hashlib.sha256(original).hexdigest()==expected,f'Executed source differs from preregistration: {path}'


def verify_execution_commit(commit):
    assert isinstance(commit,str) and re.fullmatch('[0-9a-f]{40}',commit),'Missing full execution commit identity'
    result=subprocess.run(['git','merge-base','--is-ancestor',PREREG,commit],capture_output=True)
    assert result.returncode==0,'Execution commit must exist and descend from preregistration'


def compare(actual,expected,path='model'):
    if isinstance(expected,dict):
        assert set(actual)==set(expected),f'{path}: dictionary identity mismatch'
        for key,value in expected.items():compare(actual[key],value,f'{path}.{key}')
    elif isinstance(expected,list):
        assert len(actual)==len(expected),f'{path}: length mismatch'
        for k,value in enumerate(expected):compare(actual[k],value,f'{path}[{k}]')
    elif isinstance(expected,(float,np.floating)):
        close(actual,expected,path)
    else:assert actual==expected,f'{path}: {actual!r} != {expected!r}'


def reconstruct_models(cache,saved):
    """Native source closes -> disjoint OLS/AR1/ADF, no strategy helpers."""
    fullgrid=pd.date_range(START,END,freq='min',inclusive='left').as_unit('ns')
    columns={}
    for symbol in runner.SYMBOLS:
        frame=pd.read_parquet(cache/symbol/'bars.parquet',columns=['timestamp','instrument_id','duration_seconds','close'])
        clock=pd.DatetimeIndex(frame.timestamp).as_unit('ns')
        iid='binance:perpetual:'+('1000PEPEUSDT' if symbol=='PEPEUSDT' else symbol)
        assert clock.equals(fullgrid) and frame.instrument_id.eq(iid).all() and frame.duration_seconds.eq(60).all()
        availability=clock+pd.Timedelta(minutes=2)
        selected=(availability.minute==1)&(availability<TRAIN_END)
        values=frame.close.to_numpy(dtype=float)[selected]
        assert np.isfinite(values).all() and (values>0).all()
        columns[symbol]=values
    index=availability[selected]
    expected=pd.date_range(START+pd.Timedelta(hours=1,minutes=1),TRAIN_END-pd.Timedelta(hours=1)+pd.Timedelta(minutes=1),freq='h').as_unit('ns')
    assert index.equals(expected)
    prices=pd.DataFrame(columns,index=index)
    beta_prices=prices.loc[prices.index<BETA_END];calibration=prices.loc[prices.index>=BETA_END]
    returns=np.diff(np.log(beta_prices.to_numpy()),axis=0)
    factors=returns[:,:2];design=np.c_[np.ones(len(factors)),factors]
    condition=float(np.linalg.cond((factors-factors.mean(axis=0))/factors.std(axis=0)))
    fitted={}
    for k,alt in enumerate(runner.ALTS,2):
        coefficients,_,rank,_=np.linalg.lstsq(design,returns[:,k],rcond=None)
        alpha,b,e=map(float,coefficients)
        logs=np.log(calibration/calibration.iloc[0])
        elapsed=(calibration.index-calibration.index[0]).total_seconds()/3600
        x=(logs[alt]-b*logs.BTCUSDT-e*logs.ETHUSDT-alpha*elapsed).to_numpy()
        ou_design=np.c_[np.ones(len(x)-1),x[:-1]]
        ou_coefficients,_,ou_rank,_=np.linalg.lstsq(ou_design,x[1:],rcond=None)
        assert ou_rank==2,'Degenerate actual calibration requires explicit independent handling'
        intercept,phi=map(float,ou_coefficients)
        variance=float(np.var(x[1:]-ou_design@ou_coefficients,ddof=2))
        valid=bool(0<phi<1 and variance>0 and math.isfinite(variance))
        mu=intercept/(1-phi) if valid else None
        sigma=math.sqrt(variance/(1-phi**2)) if valid else None
        half_life=-math.log(2)/math.log(phi) if valid else None
        ou={'valid':valid,'intercept':intercept,'phi':phi,'innovation_variance':variance,
            'mu':mu,'sigma':sigma,'half_life_hours':half_life}
        adf=adfuller(x,maxlag=24,regression='c',autolag=None)
        adf_result={'statistic':float(adf[0]),'pvalue':float(adf[1]),'used_lag':int(adf[2]),
                    'nobs':int(adf[3]),'critical_values':{key:float(value) for key,value in adf[4].items()}}
        halves=np.array_split(x,2);means=[float(y.mean()) for y in halves]
        variances=[float(np.var(y,ddof=1)) for y in halves];ratio=variances[1]/variances[0]
        checks={'identified_beta':rank==3 and np.isfinite(condition) and condition<=100,
                'bounded_beta':abs(b)+abs(e)<=4,'valid_ou':valid,
                'intraday_half_life':bool(valid and 1<=half_life<=24),'conditional_adf':adf[1]<=.01,
                'stable_half_means':bool(valid and all(abs(m-mu)<=sigma for m in means)),
                'stable_half_variances':bool(.25<=ratio<=4)}
        fitted[alt]={'eligible':bool(all(checks.values())),'alpha':alpha,'beta_btc':b,'beta_eth':e,
            'origin_available_at':str(calibration.index[0]),'origin_price_time':str(calibration.index[0]-pd.Timedelta(minutes=1)),
            'origin_prices':{s:float(calibration.iloc[0][s]) for s in runner.SYMBOLS},'phi':phi,'mu':mu,'sigma':sigma,
            'diagnostics':{'beta_sample_count':len(returns),'calibration_sample_count':len(x),
                'standardized_factor_condition':condition,'beta_rank':int(rank),
                'beta_last_available_at':str(beta_prices.index[-1]),'calibration_first_available_at':str(calibration.index[0]),
                'calibration_last_available_at':str(calibration.index[-1]),'ou':ou,'adf':adf_result,
                'half_means':means,'half_variances':variances,'variance_ratio':ratio,
                'calibration_terminal_residual':float(x[-1]),'checks':checks,
                'failed_checks':[key for key,value in checks.items() if not value]}}
        compare(saved['assets'][alt],fitted[alt],alt)
    assert set(saved['assets'])==set(runner.ALTS) and saved['candidate_count_cumulative']==25
    assert saved['family']=='btc_eth_hedged_residual_convergence'
    assert saved['beta_fit_end_exclusive']==str(BETA_END) and saved['calibration_end_exclusive']==str(TRAIN_END)
    assert not any(item['eligible'] for item in fitted.values()),'This certificate is for the actual no-admissible cohort'
    return fitted


def assert_inactive(tables,exposure):
    for ledger in ['fills','funding','trades','positions','events']:
        assert tables[ledger].empty,f'Unexpected {ledger} activity despite six inadmissible models'
    equity=tables['equity']
    for field in ['cash','equity','available_margin']:close(equity[field],100000.,f'Inactive {field}')
    for field in ['collateral','margin_used','maintenance_margin','long_exposure','short_exposure','gross_exposure',
                  'net_exposure','unrealized_pnl','realized_pnl','funding_pnl','trading_fees','slippage_cost','liquidation_fees','turnover']:
        close(equity[field],0.,f'Inactive {field}')
    assert pd.DatetimeIndex(exposure.timestamp).equals(pd.DatetimeIndex(equity.timestamp))
    for field in ['cash','equity']:close(exposure[field],equity[field],f'Observer {field}')
    for field in ['gross_exposure','net_exposure','frozen_factor_exposure_BTCUSDT','frozen_factor_exposure_ETHUSDT']:
        close(exposure[field],0.,f'Observer {field}')
    for symbol in runner.SYMBOLS:
        for prefix in ['quantity','collateral','unrealized']:close(exposure[f'{prefix}_{symbol}'],0.,f'Observer {prefix} {symbol}')


def verify_phase(cache,out,phase,lock):
    name,begin,stop,stress=phase;path=out/'trials'/name
    completion=runner.read(path/'completion.json');outputs=runner.output_files(path)
    assert completion=={'phase':name,'stress':stress,'source_lock_sha256':sha(out/'source_lock.json'),
                       'models_sha256':sha(out/'models.json'),'outputs_sha256':outputs}
    assert len(outputs)==20
    metadata=runner.read(path/'metadata.json');parameters=metadata['parameters']
    for key,value in {'family':runner.FAMILY,'phase':name,'begin':str(begin),'stop':str(stop),'stress':stress,
                      'source_lock_sha256':sha(out/'source_lock.json'),'models_sha256':sha(out/'models.json')}.items():
        assert parameters[key]==value,f'Phase parameter {key}'
    verify_execution_commit(metadata['git_commit'])
    assert metadata['source_sha256']=={name.removeprefix('aster/'):value for name,value in lock['sources'].items() if name.startswith('aster/')}
    specs=metadata['instruments'];expected_ids={'binance:perpetual:'+('1000PEPEUSDT' if s=='PEPEUSDT' else s) for s in runner.SYMBOLS}
    assert len(specs)==8 and {spec['id'] for spec in specs}==expected_ids
    assert all(spec['market_type']=='perpetual' and spec['taker_bps']==(10 if stress else 5) for spec in specs)
    config=metadata['engine']
    for key,value in {'initial_balances':{'binance':100000.},'leverage':1,'margin_mode':'isolated','record_every':1,
                      'max_gross_leverage':1,'max_position_pct':.5,'execution_delay_bars':int(stress),
                      'slippage_bps':16 if stress else 8,'participation':.025 if stress else .05}.items():assert config[key]==value
    tables={name:pd.read_parquet(path/f'{name}.parquet') for name in runner.LEDGERS}
    exposure=pd.read_parquet(path/'exposure.parquet');assert_inactive(tables,exposure)
    equity=tables['equity'];clock=pd.DatetimeIndex(equity.timestamp).as_unit('ns')
    expected_clock=pd.date_range(begin,stop,freq='min').as_unit('ns')
    for symbol in runner.SYMBOLS:
        source=pd.read_parquet(cache/symbol/'bars.parquet',columns=['timestamp','mark_open','mark_price'])
        source=source.loc[source.timestamp.ge(begin)&source.timestamp.lt(stop)]
        funding=pd.read_parquet(cache/symbol/'funding.parquet')
        funding=funding.loc[funding.timestamp.ge(begin)&funding.timestamp.le(stop)]
        expected_clock=expected_clock.union(pd.DatetimeIndex(funding.timestamp).as_unit('ns'))
        mark=pd.Series([source.mark_price.iloc[-1]],index=pd.DatetimeIndex([stop]))
        settled=pd.Series(funding.mark_price.to_numpy(),index=pd.DatetimeIndex(funding.timestamp))
        opened=pd.Series(source.mark_open.to_numpy(),index=pd.DatetimeIndex(source.timestamp))
        history=pd.concat([mark,settled,opened]).groupby(level=0).last()
        allclock=history.index.union(clock).sort_values()
        expected_marks=history.reindex(allclock).ffill().reindex(clock).to_numpy(copy=True)
        expected_marks[0]=0.  # Engine initial baseline precedes first open/settlement.
        close(exposure[f'mark_{symbol}'].to_numpy(),expected_marks,f'Observed actual mark {symbol}')
    assert clock.equals(expected_clock.sort_values()),'Every actual minute and settlement clock must be retained'
    scores=runner.read(path/'metrics.json')
    rebuilt_metrics=runner.json_safe(runner.metrics(equity,tables['trades'],tables['fills']))
    for key,value in rebuilt_metrics.items():compare(scores[key],value,f'{name}.metrics.{key}')
    for key in ['total_return','max_drawdown','funding_pnl','trading_pnl','trading_fees','slippage_cost','liquidation_fees',
                'indicative_exit_fee_reserve','indicative_exit_slippage_reserve','indicative_exit_reserve_total',
                'return_after_indicative_exit_reserve','liquidation_event_count','open_position_count','fill_count','trade_count']:
        close(scores[key],0.,f'Inactive metric {key}')
    assert scores['sharpe'] is None and scores['final_equity']==scores['initial_equity']==100000.
    legs=pd.read_csv(path/'leg_contributions.csv')
    assert len(legs)==8 and set(legs.symbol)==set(runner.SYMBOLS) and set(legs.instrument_id)==expected_ids
    for key in ['net_pnl','fill_count','open_quantity','funding_cash']:close(legs[key],0.,f'Leg {key}')
    diagnostics=runner.read(path/'strategy_diagnostics.json')
    assert diagnostics=={'events':[],'admission_failures':{},'terminal_state':'IDLE','terminal_active_baskets':{},'terminal_transaction':None,'terminal_cleanup_order_count':0}
    assert not runner.read(path/'quality.json')['errors']
    return {'outputs_sha256':outputs,'equity_snapshots':len(equity),'fills':0,'funding_payments':0,'terminal_positions':0,'liquidations':0}


def verify(cache,out,final=False):
    cache,out=Path(cache),Path(out);lock=runner.guard(cache,out);verify_source_anchor(lock);models=runner.verified_models(out)
    reconstructed=reconstruct_models(cache,models)
    trials={}
    for phase in runner.PHASES:
        if (out/'trials'/phase[0]/'completion.json').exists():trials[phase[0]]=verify_phase(cache,out,phase,lock)
    receipt={'complete':False,'errors':[],'expected_trials':5,'completed_trials':len(trials),'trials':trials,
             'source_lock_sha256':sha(out/'source_lock.json'),'models_sha256':sha(out/'models.json'),
             'preregistration_commit':PREREG,'executed_sources_match_preregistration':True,
             'source_files_checked':len(lock['sources']),'input_files_checked':len(lock['inputs']),
             'training_model_reconstruction_passed':True,'eligible_assets':[],
             'asset_diagnostics':{alt:{'half_life_hours':m['diagnostics']['ou']['half_life_hours'],
                                     'adf_pvalue':m['diagnostics']['adf']['pvalue'],'failed_checks':m['diagnostics']['failed_checks']}
                                  for alt,m in reconstructed.items()},
             'limitations':'One fixed no-admissible exploratory family; no trading evidence or new successful strategy.'}
    receipt['auditor_sha256']=sha(Path(__file__))
    if final:
        assert set(trials)=={phase[0] for phase in runner.PHASES},'Require all five completed trials'
        assert {path.name for path in (out/'trials').iterdir()}==set(trials),'Extra hidden trajectories'
        saved=runner.read(out/'summary.json')
        with tempfile.TemporaryDirectory(prefix='residual-summary-audit-') as directory:
            temporary=Path(directory)
            for name in ['source_lock.json','models.json','estimation_receipt.json','input_verification.json','executed_source','trials']:
                (temporary/name).symlink_to((out/name).resolve(),target_is_directory=(out/name).is_dir())
            rebuilt=runner.summarize(cache,temporary)
            compare(saved,rebuilt,'summary')
        assert not saved['passes_hurdles'] and not saved['target_alt_participants']
        assert saved['anchored_month_returns']==[0.,0.,0.]
        assert saved['conditional_interval']['comparison_count']==25
        assert saved['conditional_interval']['return_interval95']==saved['conditional_interval']['return_interval_bonferroni25']==[0.,0.]
        expected_true={'minute_drawdown_at_most_twenty_percent','no_liquidation_all_five_runs'}
        assert {name for name,value in saved['gates'].items() if value}==expected_true
        receipt.update(complete=True,summary_sha256=sha(out/'summary.json'),trajectory_reconstruction_passed=True,
                       summary_reconstruction_passed=True,independent_gates_reconstruction_passed=True,
                       passes_hurdles=False,zero_width_interval_is_cash_only=True)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cache',default='data_cache/minute-perpetual-1y');parser.add_argument('--out',default='results/residual-convergence-1y-v1');parser.add_argument('--final',action='store_true');parser.add_argument('--receipt',default='audit/residual_independent_audit.json');args=parser.parse_args()
    result=verify(args.cache,args.out,args.final)
    runner.dump(args.receipt,result)
    print({key:value for key,value in result.items() if key not in ['trials']})
