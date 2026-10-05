"""Disjoint-training residual model; no historical fitting on import.

Prices use native contracts but spot-underlying labels. Every index is the
actual assumed availability time: completed close plus one minute.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd

START = pd.Timestamp('2025-10-05', tz='UTC')
BETA_END = pd.Timestamp('2026-01-05', tz='UTC')
TRAIN_END = pd.Timestamp('2026-04-05', tz='UTC')
EVAL_START = pd.Timestamp('2026-07-05', tz='UTC')
END = pd.Timestamp('2026-10-05', tz='UTC')
SYMBOLS = ['BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT']
ALTS = SYMBOLS[2:]


def validate_prices(frame):
    if not isinstance(frame.index,pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError('UTC-aware availability index required')
    if str(frame.index.tz) != 'UTC' or not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError('Sorted unique UTC availability times required')
    if set(frame.columns) != set(SYMBOLS):
        raise ValueError('Exactly eight native-contract price columns required')
    values = frame[SYMBOLS].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not (values>0).all():
        raise ValueError('Prices must be finite positive observed closes')


def hourly_prices(minute_prices):
    """Each hourly close is the complete hour's final actual minute close."""
    validate_prices(minute_prices)
    mask = (minute_prices.index.minute==1) & (minute_prices.index.second==0)
    return minute_prices.loc[mask,SYMBOLS].copy()


def residual(prices,asset,model):
    """One fixed origin and frozen hourly drift; no fitting or rebasing."""
    origin = model['origin_prices']
    elapsed = (prices.index-pd.Timestamp(model['origin_available_at'])).total_seconds()/3600
    return (np.log(prices[asset]/origin[asset])
        - model['beta_btc']*np.log(prices['BTCUSDT']/origin['BTCUSDT'])
        - model['beta_eth']*np.log(prices['ETHUSDT']/origin['ETHUSDT'])
        - model['alpha']*elapsed)


def fit_ou(series):
    """Hourly AR1 diagnostic of a separately observed cumulative residual."""
    values = np.asarray(series,dtype=float)
    if len(values)<100 or not np.isfinite(values).all():
        raise ValueError('At least100 finite hourly residual observations required')
    design = np.column_stack([np.ones(len(values)-1),values[:-1]])
    coef,_,rank,_ = np.linalg.lstsq(design,values[1:],rcond=None)
    if rank!=2:
        return {'valid':False,'reason':'degenerate_residual','phi':None,'mu':None,'sigma':None}
    intercept,phi = map(float,coef)
    innovation = values[1:]-design@coef
    variance = float(np.var(innovation,ddof=2))
    valid = 0<phi<1 and variance>0 and math.isfinite(variance)
    out = {'valid':bool(valid),'intercept':intercept,'phi':phi,'innovation_variance':variance,
           'mu':None,'sigma':None,'half_life_hours':None}
    if valid:
        out.update(mu=intercept/(1-phi),sigma=math.sqrt(variance/(1-phi**2)),
                   half_life_hours=-math.log(2)/math.log(phi))
        if not all(math.isfinite(out[k]) for k in ['mu','sigma','half_life_hours']):
            out.update(valid=False,reason='nonfinite_ou')
    return out


def fit_asset(training_prices,asset):
    """All numerical inputs are cut to the fixed training period first."""
    from statsmodels.tsa.stattools import adfuller
    training = training_prices.loc[training_prices.index<TRAIN_END,SYMBOLS].copy()
    validate_prices(training)
    if asset not in ALTS:
        raise ValueError('Only six declared target alts may be fitted')
    expected = pd.date_range(START+pd.Timedelta(hours=1,minutes=1),
                             TRAIN_END-pd.Timedelta(hours=1)+pd.Timedelta(minutes=1),freq='1h')
    if not training.index.equals(expected):
        raise ValueError('Exact within-year training hourly grid required; no warmup/future interpolation')
    fit = training.loc[training.index<BETA_END]
    calibration = training.loc[training.index>=BETA_END]
    returns = np.log(fit).diff().iloc[1:]
    factors = returns[['BTCUSDT','ETHUSDT']].to_numpy()
    target = returns[asset].to_numpy()
    deviations = factors.std(axis=0)
    conditioned = np.inf
    if np.all(deviations>0):
        conditioned = float(np.linalg.cond((factors-factors.mean(axis=0))/deviations))
    design = np.column_stack([np.ones(len(factors)),factors])
    coef,_,rank,_ = np.linalg.lstsq(design,target,rcond=None)
    alpha,beta_btc,beta_eth = map(float,coef)
    result = {'eligible':False,'alpha':alpha,'beta_btc':beta_btc,'beta_eth':beta_eth,
        'origin_available_at':str(calibration.index[0]),
        'origin_price_time':str(calibration.index[0]-pd.Timedelta(minutes=1)),
        'origin_prices':{s:float(calibration.iloc[0][s]) for s in SYMBOLS},
        'phi':None,'mu':None,'sigma':None,'diagnostics':{
            'beta_sample_count':len(returns),'calibration_sample_count':len(calibration),
            'standardized_factor_condition':conditioned,'beta_rank':int(rank),
            'beta_last_available_at':str(fit.index[-1]),
            'calibration_first_available_at':str(calibration.index[0]),
            'calibration_last_available_at':str(calibration.index[-1])}}
    checks = {'identified_beta':rank==3 and math.isfinite(conditioned) and conditioned<=100,
              'bounded_beta':abs(beta_btc)+abs(beta_eth)<=4}
    x = residual(calibration,asset,result)
    ou = fit_ou(x)
    result.update({key:ou.get(key) for key in ['phi','mu','sigma']})
    checks['valid_ou'] = bool(ou['valid'])
    checks['intraday_half_life'] = bool(ou['valid'] and 1<=ou['half_life_hours']<=24)
    if float(np.var(x.to_numpy()))>0:
        adf = adfuller(x.to_numpy(),maxlag=24,regression='c',autolag=None)
        adf_result = {'statistic':float(adf[0]),'pvalue':float(adf[1]),'used_lag':int(adf[2]),
                      'nobs':int(adf[3]),'critical_values':{k:float(v) for k,v in adf[4].items()}}
    else:
        adf_result = {'statistic':None,'pvalue':None,'used_lag':24,'nobs':None,'critical_values':{}}
    checks['conditional_adf'] = adf_result['pvalue'] is not None and adf_result['pvalue']<=.01
    halves = np.array_split(x.to_numpy(),2)
    means = [float(block.mean()) for block in halves]
    variances = [float(np.var(block,ddof=1)) for block in halves]
    ratio = variances[1]/variances[0] if variances[0]>0 else None
    checks['stable_half_means'] = bool(ou['valid'] and all(abs(m-ou['mu'])<=ou['sigma'] for m in means))
    checks['stable_half_variances'] = bool(ratio is not None and .25<=ratio<=4)
    result['diagnostics'].update(ou=ou,adf=adf_result,half_means=means,half_variances=variances,
        variance_ratio=ratio,calibration_terminal_residual=float(x.iloc[-1]),
        checks=checks,failed_checks=[k for k,v in checks.items() if not v])
    result['eligible'] = bool(all(checks.values()))
    return result


def fit_models(hourly_price_frame):
    # Filter before checking values: later prices cannot affect an earlier model.
    training = hourly_price_frame.loc[hourly_price_frame.index<TRAIN_END].copy()
    assets = {alt:fit_asset(training,alt) for alt in ALTS}
    return {'family':'btc_eth_hedged_residual_convergence','candidate_count_cumulative':25,
            'beta_fit_end_exclusive':str(BETA_END),'calibration_end_exclusive':str(TRAIN_END),
            'research_status':'exploratory reused year; conditional model diagnostics only',
            'assets':assets}


def build_features(minute_price_frame,models):
    validate_prices(minute_price_frame)
    output = minute_price_frame.rename(columns={s:f'price_{s}' for s in SYMBOLS}).copy()
    for alt in ALTS:
        model = models['assets'][alt]
        x = residual(minute_price_frame,alt,model)
        before_origin = minute_price_frame.index<pd.Timestamp(model['origin_available_at'])
        x.loc[before_origin] = np.nan
        output[f'x_{alt}'] = x
        output[f'z_{alt}'] = (x-model['mu'])/model['sigma'] if model['eligible'] else np.nan
        output.loc[output.index<TRAIN_END,f'z_{alt}'] = np.nan
    return output
