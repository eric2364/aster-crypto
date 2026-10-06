"""Cohort-specific independent proof of zero economic admissions, not policy replay.

Reads immutable features and zero-activity exports only. No Engine, strategy,
signal, frozen runner imports or estimation. Fraction arithmetic is independent.
"""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
import sys
from pathlib import Path
import pandas as pd
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audit import verify_cross_venue_outputs as financial

REPO=Path(__file__).resolve().parents[1]
ANCHOR='98fe45a55866ccfd1fa5a4e68deb52a127ff7ff2'
INPUT_ANCHOR='1820b8278bfae8a3775fce3b0ee15be8ac2a5448'
SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
VENUES=('binance','bybit')
VALID=pd.Timestamp('2026-04-05',tz='UTC');EVAL=pd.Timestamp('2026-07-05',tz='UTC');END=pd.Timestamp('2026-10-05',tz='UTC')
PHASES=[(f'validation{k+1}',VALID+pd.DateOffset(months=k),VALID+pd.DateOffset(months=k+1),False,'primary') for k in range(3)]+[(n,EVAL,END,s,v) for n,s,v in [('evaluation',False,'primary'),('evaluation_stress',True,'primary'),('evaluation_alternative',False,'alternative'),('evaluation_alternative_stress',True,'alternative')]]
HORIZON=pd.Timedelta(hours=168)


def check(ok,message):
    if not ok:raise AssertionError(message)

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_bytes())
def iid(v,s):return v+':perpetual:'+('1000PEPEUSDT' if s=='PEPEUSDT' else s)


def fraction(value,positive=False):
    check(not isinstance(value,(bool,np.bool_)) and math.isfinite(float(value)),'Finite numeric value required')
    result=Fraction(str(value))
    check(not positive or result>0,'Positive native rule/price required')
    return result


def common_grid(first,second):
    steps=[fraction(s['lot_size'],True) for s in (first,second)]
    denominator=math.lcm(*(s.denominator for s in steps))
    integers=[s.numerator*(denominator//s.denominator) for s in steps]
    return Fraction(math.lcm(*integers),denominator)


def validate_pair(first,second,symbol):
    for venue,spec in zip(VENUES,(first,second)):
        check(spec['id']==iid(venue,symbol) and spec['exchange']==venue and spec['symbol']==spec['id'].split(':')[-1]
              and spec['base']==spec['symbol'][:-4] and spec['quote']=='USDT' and spec['market_type']=='perpetual'
              and spec['contract_type']=='linear' and spec['multiplier']==1,'Wrong native paired instrument')
        for key in ('lot_size','min_quantity','min_notional'):fraction(spec[key],True)
    check(first['base']==second['base'],'Different native base units cannot hedge')


def admission(row,first,second,symbol):
    """Economic admission only. Any passing pair fails this zero-cohort audit.

    Margin could reject an admitted intent; therefore this deliberately uses a
    conservative upper bound on eligibility and cannot certify a trading cohort.
    """
    validate_pair(first,second,symbol)
    values={}
    for venue in VENUES:
        flag=row[f'valid_{venue}_{symbol}']
        check(not pd.isna(flag) and flag in (True,False,0,1),'Malformed validity flag')
        if not bool(flag):return {'eligible':False,'reason':'invalid_feature'}
        rate=row[f'yield_{venue}_{symbol}'];price=row[f'price_{venue}_{symbol}']
        check(math.isfinite(float(rate)) and math.isfinite(float(price)) and float(price)>0,'Corrupt valid available feature')
        values[venue]=(fraction(rate),fraction(price,True))
    rb,pb=values['binance'];ry,py=values['bybit'];gap=ry-rb
    if not gap:return {'eligible':False,'reason':'zero_gap'}
    grid=common_grid(first,second)
    ideal=min(Fraction(1250)/pb,Fraction(1250)/py)
    exact_quantity=(ideal//grid)*grid
    # Include the coordinator's float division -> decimal repr -> exact floor path.
    float_ideal=Fraction(str(min(1250./float(pb),1250./float(py))))
    float_quantity=(float_ideal//grid)*grid
    quantity=max(exact_quantity,float_quantity)
    minimum=max(fraction(first['min_quantity'],True),fraction(second['min_quantity'],True))
    if quantity<minimum:return {'eligible':False,'reason':'common_quantity_minimum'}
    notional_epsilon=Fraction(1,10**9)
    exact_minimum_pass=(quantity*pb>=fraction(first['min_notional'],True)-notional_epsilon
                        and quantity*py>=fraction(second['min_notional'],True)-notional_epsilon)
    float_minimum_pass=(float(quantity)*float(pb)>=float(first['min_notional'])-1e-9
                        and float(quantity)*float(py)>=float(second['min_notional'])-1e-9)
    if not (exact_minimum_pass or float_minimum_pass):
        return {'eligible':False,'reason':'opening_notional_minimum'}
    cost=2*quantity*(pb*Fraction(26,10000)+py*Fraction(28,10000))
    forecast=quantity*(pb+py)/2*abs(gap)*168
    exact_pass=forecast>=Fraction(3,2)*cost
    # Also conservatively detect a binary-float comparator passing at a boundary.
    # It is never permitted to erase an exact-rational admission.
    fq=float(quantity);fb=float(pb);fy=float(py);fg=float(ry)-float(rb)
    float_cost=2*fq*(fb*.0026+fy*.0028)
    float_forecast=fq*(fb+fy)/2*abs(fg)*168
    float_pass=float_forecast>=1.5*float_cost
    # Union both finite quantity paths at a comparator boundary.
    for planned in (exact_quantity,float_quantity):
        fp=float(planned)
        if fp>0:
            candidate_forecast=fp*(fb+fy)/2*abs(fg)*168
            candidate_cost=2*fp*(fb*.0026+fy*.0028)
            float_pass |= candidate_forecast>=1.5*candidate_cost
    return {'eligible':bool(exact_pass or float_pass),'reason':'economic_admission' if exact_pass or float_pass else 'stress_cost_filter',
            'direction':1 if gap>0 else -1,'native_quantity':float(quantity),
            'exact_native_quantity':float(exact_quantity),'float_ideal_native_quantity':float(float_quantity),'common_grid':str(grid),
            'forecast_carry':float(forecast),'stress_roundtrip_cost':float(cost),
            'forecast_to_cost_ratio':float(forecast/cost),'exact_admission':bool(exact_pass),'float_admission':bool(float_pass)}


def unit_cost_upper_bound(row,symbol):
    """Quantity cancels: ignore all native/margin minima conservatively."""
    if not all(bool(row[f'valid_{v}_{symbol}']) for v in VENUES):return None
    rb,ry=(fraction(row[f'yield_{v}_{symbol}']) for v in VENUES)
    pb,py=(fraction(row[f'price_{v}_{symbol}'],True) for v in VENUES)
    forecast=(pb+py)/2*abs(ry-rb)*168
    cost=2*(pb*Fraction(26,10000)+py*Fraction(28,10000))
    exact=forecast>=Fraction(3,2)*cost
    ff=(float(pb)+float(py))/2*abs(float(ry)-float(rb))*168
    fc=2*(float(pb)*.0026+float(py)*.0028)
    # Conservative uncertainty band: do not certify an approximate float boundary.
    tolerance=16*np.finfo(float).eps*max(abs(ff),abs(1.5*fc))
    return {'eligible':bool(exact or ff>=1.5*fc-tolerance),
            'unit_forecast_to_cost_ratio':float(forecast/cost)}


def phase_checks(features,specs,phase):
    name,begin,stop,stress,valuation=phase
    check(isinstance(features.index,pd.DatetimeIndex) and features.index.tz is not None and not features.index.has_duplicates
          and features.index.is_monotonic_increasing,'Invalid available feature clock')
    first=begin+pd.Timedelta(minutes=5)
    expected=pd.date_range(first,stop-HORIZON,freq='h',inclusive='left').as_unit('ns')
    check(expected.isin(features.index).all(),'Missing eligible hourly feature observation')
    reasons=Counter();eligible=[];max_ratio=0.;valid_pairs=0
    for clock in expected:
        row=features.loc[clock]
        for symbol in SYMBOLS:
            result=admission(row,specs[iid('binance',symbol)],specs[iid('bybit',symbol)],symbol)
            upper=unit_cost_upper_bound(row,symbol)
            if upper is not None:
                valid_pairs+=1
                max_ratio=max(max_ratio,upper['unit_forecast_to_cost_ratio'])
                if upper['eligible'] and not result['eligible']:
                    result={**result,**upper,'reason':'potential_unit_cost_admission_ignoring_minima'}
            reasons[result['reason']]+=1
            max_ratio=max(max_ratio,result.get('forecast_to_cost_ratio',0.))
            if result['eligible']:eligible.append({'timestamp':clock.isoformat(),'symbol':symbol,**result})
    check(not eligible,'Eligible economic admission found in zero-activity cohort: '+json.dumps(eligible[:3]))
    return {'phase':name,'begin':str(begin),'stop':str(stop),'stress':stress,'valuation':valuation,
            'hourly_clocks_checked':len(expected),'pair_decisions_checked':len(expected)*8,
            'economic_admission_count':0,'valid_pair_decisions_checked':valid_pairs,'unit_cost_upper_bound_reconstruction_passed':True,'rejection_counts':dict(sorted(reasons.items())),
            'max_forecast_to_cost_ratio':max_ratio,'required_ratio':1.5}


def zero_activity(path):
    for name in ('fills','trades','funding','positions','matched_entries','unmatched','events'):
        frame=pd.read_parquet(path/(name+'.parquet'))
        check(frame.empty,'Cohort certificate requires zero '+name+' observations')
    equity=pd.read_parquet(path/'equity.parquet');exposure=pd.read_parquet(path/'exposure.parquet')
    check(len(equity)>0 and len(equity)==len(exposure),'Missing flat account clock')
    for col,value in [('equity',100000.),('cash',100000.),('binance_cash',50000.),('bybit_cash',50000.),('binance_equity',50000.),('bybit_equity',50000.)]:
        check(equity[col].eq(value).all(),'Flat cohort wallet/equity mismatch')
    for col in ('realized_pnl','unrealized_pnl','funding_pnl','trading_fees','liquidation_fees','turnover','gross_exposure','net_exposure','margin_used'):
        check(equity[col].eq(0).all(),'Nonzero financial activity in flat cohort')
    for symbol in SYMBOLS:
        for venue in VENUES:check(exposure[f'quantity_{venue}_{symbol}'].eq(0).all(),'Actual native inventory not flat')
    diagnostics=read(path/'strategy_diagnostics.json')
    check(not diagnostics['matched_entries'] and all(e['type']=='ADMISSION_REJECTED' for e in diagnostics['events']),
          'Order/pair/risk intent exists: zero-admission certificate scope does not apply')
    return {'zero_activity_verified':True,'equity_snapshots':len(equity)}


def verify(binance,bybit,out,feature_audit):
    own_sha=sha(__file__);helper_sha=sha(financial.__file__)
    out=Path(out);feature_audit=Path(feature_audit);feature_audit_sha=sha(feature_audit)
    lock=financial.packet_guard(out)
    feature=read(feature_audit)
    check(feature.get('complete') is True and feature.get('errors')==[] and feature.get('reference_reconstruction_passed') is True,
          'Final independent feature reconstruction required')
    check(feature.get('auditor_sha256')==sha(REPO/'audit/verify_cross_venue_features.py')
          and feature.get('source_unchanged_during_audit') is True and feature.get('auditor_source_unchanged') is True,
          'Feature auditor implementation/stability differs')
    common=dict(source_lock_sha256=sha(out/'source_lock.json'),features_sha256=sha(out/'features.parquet'),feature_receipt_sha256=sha(out/'feature_receipt.json'))
    check(all(feature.get(k)==v for k,v in common.items()) and feature.get('source_anchor')==ANCHOR
          and feature.get('input_freeze_anchor')==INPUT_ANCHOR,'Feature certificate differs from frozen packet')
    features=pd.read_parquet(out/'features.parquet')
    specs={}
    for venue,root in [('binance',Path(binance)),('bybit',Path(bybit))]:
        items=read(root/'instruments.json');check(len(items)==8,'Eight native rules per venue required')
        specs.update({s['id']:s for s in items})
    check(set(specs)=={iid(v,s) for v in VENUES for s in SYMBOLS},'Exact16 native catalog required')
    trials=out/'trials';check({p.name for p in trials.iterdir()}=={p[0] for p in PHASES},'Seven exact phases required')
    records={}
    for phase in PHASES:
        name=phase[0];path=trials/name;outputs={n:sha(path/n) for n in financial.OUTPUTS}
        records[name]={'outputs_sha256':outputs,**phase_checks(features,specs,phase),**zero_activity(path)}
        check({n:sha(path/n) for n in financial.OUTPUTS}==outputs,'Phase evidence changed during no-admission audit')
    financial.packet_guard(out)
    check(sha(__file__)==own_sha and sha(financial.__file__)==helper_sha and sha(feature_audit)==feature_audit_sha,'Auditor/helper/feature certificate changed')
    return {'complete':True,'errors':[],'source_anchor':ANCHOR,'input_anchor':INPUT_ANCHOR,**common,
            'summary_sha256':sha(out/'summary.json'),'feature_audit_sha256':feature_audit_sha,
            'auditor_sha256':own_sha,'guard_helper_sha256':helper_sha,'source_unchanged_during_audit':True,
            'no_economic_admission_reconstruction_passed':True,'unit_cost_upper_bound_reconstruction_passed':True,'zero_activity_cohort_verified':True,
            'economic_admission_count':0,'pair_decisions_checked':sum(r['pair_decisions_checked'] for r in records.values()),
            'trials':records,'scope':'Cohort-specific zero-economic-admission proof; not generic strategy intent/GTC/cleanup reproduction',
            'limits':['Quantity-cancelled unit forecast/cost upper bound ignores native minima and margin acceptance; any potential pass fails this zero-cohort certificate.',
                      'Historical feature causality is certified separately; raw rates are not future announcements.',
                      'No claim of generic strategy decision reproduction for any trading cohort.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binance',default='data_cache/minute-perpetual-1y');parser.add_argument('--bybit',default='data_cache/minute-bybit-1y')
    parser.add_argument('--out',default='results/cross-venue-funding-1y-v1')
    parser.add_argument('--feature-audit',default='audit/cross_venue_feature_evidence.json')
    parser.add_argument('--certificate',default='audit/cross_venue_no_admission_evidence.json')
    args=parser.parse_args();receipt=verify(args.binance,args.bybit,args.out,args.feature_audit)
    target=Path(args.certificate);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(receipt,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({'complete':True,'economic_admissions':0,'pair_decisions_checked':receipt['pair_decisions_checked'],'certificate':str(target)}))


if __name__=='__main__':main()
