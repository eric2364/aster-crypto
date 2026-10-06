"""Independent seven-phase source, wallet, trajectory and summary reconstruction.

No imports from the engine, portfolio, strategy, signals or frozen runner.
Synthetic tests may export Engine fixtures; this auditor only reads evidence.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import importlib.metadata
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import numpy as np
import pandas as pd

REPO=Path(__file__).resolve().parents[1]
ANCHOR='98fe45a55866ccfd1fa5a4e68deb52a127ff7ff2'
INPUT_ANCHOR='1820b8278bfae8a3775fce3b0ee15be8ac2a5448'
SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
VENUES=('binance','bybit')
FAMILY='cross_venue_realized_funding_differential'
START=pd.Timestamp('2025-10-05',tz='UTC');VALID=pd.Timestamp('2026-04-05',tz='UTC');EVAL=pd.Timestamp('2026-07-05',tz='UTC');END=pd.Timestamp('2026-10-05',tz='UTC')
PHASES=[(f'validation{k+1}',VALID+pd.DateOffset(months=k),VALID+pd.DateOffset(months=k+1),False,'primary') for k in range(3)]+[(name,EVAL,END,stress,valuation) for name,stress,valuation in [('evaluation',False,'primary'),('evaluation_stress',True,'primary'),('evaluation_alternative',False,'alternative'),('evaluation_alternative_stress',True,'alternative')]]
LEDGERS=('equity','fills','trades','funding','events','positions')
OUTPUTS=tuple([f'{n}.{e}' for n in LEDGERS for e in ('csv','parquet')]+['metadata.json','metrics.json','source_manifest.json','quality.json','exposure.csv','exposure.parquet','leg_contributions.csv','pair_contributions.csv','strategy_diagnostics.json','unmatched.csv','unmatched.parquet','matched_entries.csv','matched_entries.parquet'])
EPS=1e-10


def check(ok,message):
    if not ok:raise AssertionError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def iid(venue,symbol):return venue+':perpetual:'+('1000PEPEUSDT' if symbol=='PEPEUSDT' else symbol)


def close(actual,expected,label='value'):
    if expected is None:check(actual is None or pd.isna(actual),label+': expected null');return
    a,b=np.asarray(actual,dtype=float),np.asarray(expected,dtype=float)
    check(a.shape==b.shape or b.ndim==0,label+': shape mismatch')
    check(np.allclose(a,b,rtol=2e-10,atol=1e-8,equal_nan=True),label+': numeric mismatch')


def compare(actual,expected,label='value'):
    if isinstance(expected,dict):
        check(isinstance(actual,dict) and set(actual)==set(expected),label+': keys differ')
        for k,v in expected.items():compare(actual[k],v,label+'.'+k)
    elif isinstance(expected,(list,tuple)):
        check(isinstance(actual,(list,tuple)) and len(actual)==len(expected),label+': length differs')
        for k,v in enumerate(expected):compare(actual[k],v,label+f'[{k}]')
    elif isinstance(expected,(float,np.floating)):close(actual,expected,label)
    else:check(actual==expected,label+': identity mismatch')


def clocks(series):
    check(isinstance(series.dtype,pd.DatetimeTZDtype) and str(series.dt.tz)=='UTC','UTC timestamps required')
    return series.dt.as_unit('ns').array.asi8


def configuration(stress):
    return dict(initial_balances={'binance':50000.,'bybit':50000.},margin_mode='cross',leverage=1,max_gross_leverage=.5,max_position_pct=.25,fill_model='volume_aware',participation=.025 if stress else .05,slippage_bps=16 if stress else 8,slippage_model='fixed',spread_bps=2.,impact_bps=10.,latency_ms=0,execution_delay_bars=int(stress),seed=42,funding_enabled=True,record_every=1)


def committed_file(commit,path):
    return subprocess.run(['git','show',commit+':'+path],cwd=REPO,capture_output=True,check=True).stdout


def verify_input_anchor(out):
    for name in ('source_lock.json','input_verification.json'):
        check((Path(out)/name).read_bytes()==committed_file(INPUT_ANCHOR,'docs/cross_venue_preregistration/'+name),'Input packet differs from committed pre-outcome bytes: '+name)
    prereg=json.loads(committed_file(INPUT_ANCHOR,'docs/cross_venue_preregistration/preregistration.json'))
    check(prereg['source_commit']==ANCHOR and prereg['source_lock_sha256']==sha(Path(out)/'source_lock.json') and prereg['input_verification_sha256']==sha(Path(out)/'input_verification.json') and prereg['historical_features_exist'] is False and prereg['trial_directory_exists'] is False,'Input preregistration identity differs')
    lock=read(Path(out)/'source_lock.json')
    check(len(lock['sources'])==prereg['source_files'] and len(lock['inputs'])==prereg['input_files'],'Exact committed source/input sets differ')


def packet_guard(out):
    out=Path(out);verify_input_anchor(out);lock=read(out/'source_lock.json')
    check(lock['family']==FAMILY and lock['candidate_count_cumulative']==26,'Wrong family/count')
    check(lock['phases']==[[n,str(a),str(b),s,v] for n,a,b,s,v in PHASES],'Wrong seven phases')
    runtime={'python':sys.version,**{p:importlib.metadata.version(p) for p in ('numpy','pandas','pyarrow','statsmodels','scipy','plotly')}}
    check(lock['runtime']==runtime,'Frozen runtime differs')
    for relative,expected in lock['sources'].items():
        check(not Path(relative).is_absolute() and '..' not in Path(relative).parts,'Unsafe executed source path')
        committed=subprocess.run(['git','show',ANCHOR+':'+relative],cwd=REPO,capture_output=True,check=True).stdout
        check(hashlib.sha256(committed).hexdigest()==expected,'Source differs from reviewed commit: '+relative)
        check(sha(REPO/relative)==expected and sha(out/'executed_source'/relative)==expected,'Source/archive differs: '+relative)
    for path,expected in lock['inputs'].items():check(sha(path)==expected,'Frozen input differs: '+path)
    check(read(out/'input_verification.json')==lock['input_verification'],'Input verification receipt differs')
    check(len(lock['input_verification']['binance'])==8 and lock['input_verification']['bybit_raw_reparse_verified'] is True,'Incomplete source verification')
    receipt=read(out/'feature_receipt.json')
    check(receipt['source_lock_sha256']==sha(out/'source_lock.json') and receipt['features_sha256']==sha(out/'features.parquet'),'Feature packet hash differs')
    return lock


def expected_parameters(out,phase):
    n,a,b,s,v=phase
    return dict(family=FAMILY,phase=n,begin=str(a),stop=str(b),stress=s,valuation=v,source_lock_sha256=sha(out/'source_lock.json'),features_sha256=sha(out/'features.parquet'),feature_receipt_sha256=sha(out/'feature_receipt.json'),research_status='exploratory reused year; candidate26')


def expected_specs(binance,bybit,stress):
    result=[]
    for venue,root in [('binance',binance),('bybit',bybit)]:
        items=read(Path(root)/'instruments.json')
        check(len(items)==8 and {x['id'] for x in items}=={iid(venue,s) for s in SYMBOLS},'Wrong catalog universe')
        for item in items:
            spec=dict(item);spec['maker_bps']=spec['taker_bps']=(10 if venue=='binance' else 12) if stress else (5 if venue=='binance' else 6)
            check(spec['exchange']==venue and spec['symbol']==spec['id'].split(':')[-1] and spec['base']==spec['symbol'][:-4] and spec['quote']=='USDT' and spec['market_type']=='perpetual' and spec['contract_type']=='linear' and spec['multiplier']==1,'Wrong native contract')
            result.append(spec)
    return sorted(result,key=lambda x:x['id'])


def source_inputs(binance,bybit,phase):
    _,begin,stop,_,valuation=phase
    bars={};fund=[]
    for venue,root in [('binance',binance),('bybit',bybit)]:
        for symbol in SYMBOLS:
            identity=iid(venue,symbol)
            source=pd.read_parquet(Path(root)/symbol/'bars.parquet')
            f=pd.read_parquet(Path(root)/symbol/'funding.parquet')
            check(source.instrument_id.eq(identity).all() and f.instrument_id.eq(identity).all(),'Native input identity differs')
            check(pd.DatetimeIndex(source.timestamp).as_unit('ns').equals(pd.date_range(START,END,freq='min',inclusive='left').as_unit('ns')) and source.duration_seconds.eq(60).all(),'Incomplete fixed-year minute input grid')
            f=f.loc[f.timestamp.ge(begin)&f.timestamp.le(stop)].copy()
            if venue=='bybit' and valuation=='alternative':
                indices=np.searchsorted(clocks(source.end),clocks(f.timestamp),side='right')-1
                check((indices>=0).all(),'No completed source mark predecessor')
                f['mark_price']=source.mark_price.to_numpy()[indices]
                f['mark_price_source']='latest_completed_mark_close_at_or_before_settlement'
            bars[identity]=source.loc[source.timestamp.ge(begin)&source.timestamp.lt(stop)].copy()
            fund.append(f)
    return bars,pd.concat(fund,ignore_index=True)


def csv_hash(frames):
    # Same normalized concatenation schema, but stream each constituent instead of allocating a combined frame.
    columns=[]
    for frame in frames:
        columns.extend(c for c in frame if c not in columns)
    h=hashlib.sha256()
    for k,frame in enumerate(frames):
        text=frame.reindex(columns=columns).to_csv(index=False,header=k==0,float_format='%.17g')
        h.update(text.encode())
    return h.hexdigest()


def endpoint_returns(frame):
    index=pd.DatetimeIndex(frame.timestamp).as_unit('ns').copy()
    check(index.is_monotonic_increasing and not index.has_duplicates,'Equity clock must be unique and chronological')
    values=frame.equity.to_numpy(dtype=float)
    if index[-1]==index[-1].normalize():
        stamps=index.asi8.copy();stamps[-1]-=1000;index=pd.to_datetime(stamps,utc=True)
    series=pd.Series(values,index=index)
    daily=series.resample('D').last().ffill();previous=daily.shift(1);previous.iloc[0]=values[0]
    result=daily/previous-1;result[(previous<=0)|(daily<0)]=np.nan
    if len(series)==1 or (series.index[1:].normalize()!=series.index[0].normalize()).all():result=result.iloc[1:]
    return result


def interval(frame):
    values=endpoint_returns(frame).dropna().to_numpy()
    if len(values)<7 or (values<=-1).any():return dict(available=False,reason='insufficient/invalid daily observations')
    n=len(values);rng=np.random.default_rng(42)
    starts=rng.integers(0,n,size=(10000,(n+6)//7))
    selected=((starts[:,:,None]+np.arange(7))%n).reshape(10000,-1)[:,:n]
    totals=np.expm1(np.log1p(values[selected]).sum(axis=1))
    return dict(available=True,method='conditional circular seven-day blocks; 10000 draws; seed42',comparison_count=26,tails=[.05/52,1-.05/52],return_interval95=np.quantile(totals,[.025,.975]).tolist(),return_interval_bonferroni26=np.quantile(totals,[.05/52,1-.05/52]).tolist(),limitations='conditional fixed reused year; no cure for adaptive research')


class Replay:
    """Independent linear-contract arithmetic, with no principal debit on opening."""
    def __init__(self,specs,config):
        self.specs={s['id']:s for s in specs};self.ids=list(self.specs);self.config=config
        self.q={i:0. for i in self.ids};self.avg={i:0. for i in self.ids};self.mark={i:0. for i in self.ids}
        self.alloc={i:0. for i in self.ids};self.fund={i:0. for i in self.ids};self.entryfee={i:0. for i in self.ids};self.entryslip={i:0. for i in self.ids}
        self.entrytime={i:None for i in self.ids};self.entrytype={i:'' for i in self.ids}
        self.cash=dict(config['initial_balances']);self.realized=self.fees=self.slip=self.funding=self.liqfees=self.turnover=0.
        self.leg_net=defaultdict(float);self.leg_fund=defaultdict(float);self.leg_fills=defaultdict(int);self.trade_rows=[]
    def fill(self,row):
        i=row['instrument_id'];check(i in self.specs,'Unknown fill instrument');s=self.specs[i];venue=s['exchange']
        side=int(row['side']);qty=float(row['quantity']);price=float(row['price']);check(side in (-1,1) and qty>0 and price>0 and np.isfinite([qty,price]).all(),'Invalid fill')
        check(row['exchange']==venue and row['symbol']==s['symbol'] and row['market_type']=='perpetual' and row['liquidity_type']=='taker','Wrong fill native identity/liquidity')
        fee=qty*price*s['taker_bps']/10000;slip=side*(price-row['reference_price'])*qty
        old=self.q[i];closing=min(abs(old),qty) if old*side<0 else 0.;opening=qty-closing;fraction=closing/abs(old) if closing else 0.
        realized=closing*np.sign(old)*(price-self.avg[i]);liq=closing*price*s['liquidation_bps']/10000 if row['exit_reason']=='liquidation' else 0.
        close(row['fee'],fee,'Fill fee');close(row['slippage'],slip,'Fill slippage');close(row['realized_pnl'],realized,'Fill realized P&L')
        self.cash[venue]+=realized-fee-liq;self.realized+=realized;self.fees+=fee;self.slip+=slip;self.liqfees+=liq;self.turnover+=qty*price
        self.leg_net[i]+=realized-fee-liq;self.leg_fills[i]+=1
        if closing:
            ef=self.entryfee[i]*fraction;fp=self.fund[i]*fraction;es=self.entryslip[i]*fraction;cf=fee*closing/qty
            net=realized-ef-cf+fp-liq
            self.trade_rows.append(dict(instrument_id=i,exchange=venue,symbol=s['symbol'],market_type='perpetual',direction='long' if old>0 else 'short',order_type=self.entrytype[i],liquidity_type='taker',entry_time=self.entrytime[i],entry_price=self.avg[i],exit_time=row['timestamp'],exit_price=price,quantity=closing,leverage=1,gross_pnl=realized,maker_fees=0.,taker_fees=ef+cf,funding_pnl=fp,slippage=es+slip*closing/qty,liquidation_fee=liq,net_pnl=net,return_pct=net/(closing*self.avg[i]),holding_seconds=(row['timestamp']-self.entrytime[i]).total_seconds(),exit_reason=row['exit_reason']))
            self.entryfee[i]-=ef;self.fund[i]-=fp;self.entryslip[i]-=es;self.alloc[i]*=1-fraction
        if opening:
            if closing or abs(old)<EPS:
                self.avg[i]=price;self.entrytime[i]=row['timestamp'];self.entrytype[i]='market'
                if closing:self.alloc[i]=self.entryfee[i]=self.entryslip[i]=self.fund[i]=0.
            else:self.avg[i]=(abs(old)*self.avg[i]+opening*price)/(abs(old)+opening)
            self.alloc[i]+=opening*price;self.entryfee[i]+=fee*(opening/qty);self.entryslip[i]+=slip*(opening/qty)
        self.q[i]=old+side*qty
        if abs(self.q[i])<EPS:
            self.q[i]=self.avg[i]=self.alloc[i]=self.entryfee[i]=self.entryslip[i]=self.fund[i]=0.;self.entrytime[i]=None;self.entrytype[i]=''
    def funding_event(self,event,row):
        i=event['instrument_id'];q=self.q[i]
        if abs(q)<EPS:check(row is None,'Funding charged to flat instrument');return
        check(row is not None,'Missing actual funding cash flow')
        for k in ('instrument_id','timestamp'):check(row[k]==event[k],'Wrong funding event identity')
        for k in ('funding_rate','mark_price'):check(row[k]==event[k],'Exact source funding '+k+' differs')
        close(row['position_size'],q,'Funding native position size')
        payment=-q*event['mark_price']*event['funding_rate'];close(row['funding_payment'],payment,'Funding payment sign/amount')
        venue=self.specs[i]['exchange'];check(row['exchange']==venue and row['symbol']==self.specs[i]['symbol'],'Funding venue identity')
        self.cash[venue]+=payment;self.fund[i]+=payment;self.funding+=payment;self.leg_net[i]+=payment;self.leg_fund[i]+=payment
    def aggregates(self):
        q=np.array([self.q[i] for i in self.ids]);m=np.array([self.mark[i] for i in self.ids]);a=np.array([self.avg[i] for i in self.ids]);n=q*m;u=q*(m-a)
        used=float(abs(n).sum());long=float(n.clip(min=0).sum());short=float((-n).clip(min=0).sum());cash=sum(self.cash.values());equity=cash+u.sum()
        row=dict(cash=cash,equity=equity,collateral=used,margin_used=used,available_margin=equity-used,maintenance_margin=sum(abs(self.q[i])*self.mark[i]*self.specs[i]['maintenance_rate'] for i in self.ids),long_exposure=long,short_exposure=short,gross_exposure=used,net_exposure=long-short,unrealized_pnl=u.sum(),realized_pnl=self.realized,funding_pnl=self.funding,trading_fees=self.fees,slippage_cost=self.slip,liquidation_fees=self.liqfees,turnover=self.turnover,gross_leverage=used/equity if equity>0 else np.nan,net_leverage=(long-short)/equity if equity>0 else np.nan,margin_utilization=used/equity if equity>0 else np.nan)
        for venue in VENUES:
            ids=[i for i in self.ids if self.specs[i]['exchange']==venue];vu=sum(self.q[i]*(self.mark[i]-self.avg[i]) for i in ids);gross=sum(abs(self.q[i])*self.mark[i] for i in ids)
            row[venue+'_cash']=self.cash[venue];row[venue+'_equity']=self.cash[venue]+vu
            row[venue+'_gross_exposure']=gross;row[venue+'_margin_used']=gross;row[venue+'_available_margin']=self.cash[venue]+vu-gross
        return row
    def exposure(self):
        a=self.aggregates();row={k:a[k] for k in ('cash','equity','gross_exposure','net_exposure')}
        for venue in VENUES:
            for key in ('cash','equity','gross_exposure','available_margin','margin_used'):row[venue+'_'+key]=a[venue+'_'+key]
        for symbol in SYMBOLS:
            for venue in VENUES:
                i=iid(venue,symbol)
                for key,v in [('quantity',self.q[i]),('mark',self.mark[i]),('entry_collateral_field',self.alloc[i]),('current_mark_initial_margin',abs(self.q[i])*self.mark[i]),('unrealized',self.q[i]*(self.mark[i]-self.avg[i]))]:row[f'{key}_{venue}_{symbol}']=v
            b,y=iid('binance',symbol),iid('bybit',symbol);qb,qy=self.q[b],self.q[y];matched=min(abs(qb),abs(qy)) if qb*qy<0 else 0.
            rb,ry=abs(qb)-matched,abs(qy)-matched
            row['matched_native_'+symbol]=matched;row['unmatched_native_'+symbol]=rb+ry;row['unmatched_dollars_'+symbol]=rb*self.mark[b]+ry*self.mark[y];row['net_marked_notional_'+symbol]=qb*self.mark[b]+qy*self.mark[y]
        return row
    def liquidation_ids(self):
        result=[]
        for venue in VENUES:
            ids=[i for i in self.ids if self.specs[i]['exchange']==venue and abs(self.q[i])>EPS]
            equity=self.cash[venue]+sum(self.q[i]*(self.mark[i]-self.avg[i]) for i in ids)
            threshold=sum(abs(self.q[i])*self.mark[i]*(self.specs[i]['maintenance_rate']+(self.specs[i]['taker_bps']+self.specs[i]['liquidation_bps'])/10000) for i in ids)
            if ids and equity<=threshold:result.extend(ids)
        return result


def adverse(reference,side,spec,config):
    value=reference*(1+side*config['slippage_bps']/10000)/spec['tick_size']
    return (math.ceil(value-1e-10) if side>0 else math.floor(value+1e-10))*spec['tick_size']


def reconstruct(tables,exposure,bars,source_funding,specs,config,begin,stop):
    state=Replay(specs,config);ids=state.ids;equity=tables['equity']
    expected_clock=pd.date_range(begin,stop,freq='min').as_unit('ns').union(pd.DatetimeIndex(source_funding.timestamp).as_unit('ns').unique()).sort_values()
    check(pd.DatetimeIndex(equity.timestamp).as_unit('ns').equals(expected_clock),'Every source minute and settlement clock required')
    check(pd.DatetimeIndex(exposure.timestamp).as_unit('ns').equals(expected_clock) and len(exposure.columns)==127,'Observer clock/127-field schema differs')
    fills=tables['fills'].to_dict('records') if len(tables['fills']) else []
    funded=tables['funding'].to_dict('records') if len(tables['funding']) else []
    check([r['fill_id'] for r in fills]==list(range(1,len(fills)+1)),'Fill identities/order differ')
    fg=defaultdict(list);sg=defaultdict(list);pg={}
    for r in fills:fg[pd.Timestamp(r['timestamp'])].append(r)
    for r in funded:
        key=(pd.Timestamp(r['timestamp']),r['instrument_id']);check(key not in pg,'Duplicate funding cash flow');pg[key]=r
    for r in source_funding.to_dict('records'):sg[pd.Timestamp(r['timestamp'])].append(r)
    check(set(fg)<=set(expected_clock) and {k[0] for k in pg}<=set(expected_clock),'Fill/payment outside source clocks')
    arrays={i:{k:bars[i][k].to_numpy() for k in ('open','volume','mark_open','mark_price')} for i in ids}
    for i in ids:check(pd.DatetimeIndex(bars[i].timestamp).as_unit('ns').equals(pd.date_range(begin,stop,freq='min',inclusive='left').as_unit('ns')),'Phase grid differs')
    event_rows=tables['events'].to_dict('records') if len(tables['events']) else []
    orders={};cancelled={};accepted={};filled_events=defaultdict(list);liq_events=defaultdict(list)
    for sequence,event in enumerate(event_rows):
        event['_sequence']=sequence
        typ=event['type'];clock=pd.Timestamp(event['timestamp'])
        check(begin<=clock<=stop,'Event outside phase')
        if typ=='ORDER_SUBMITTED':
            oid=event['order_id'];check(oid not in orders,'Order identity reused');orders[oid]=event
            check(event['order_type']=='market' and event['tif']=='GTC' and not event['post_only'],'Nonpacket order type')
            close(event['quantity'],round(event['quantity']/state.specs[event['instrument_id']]['lot_size'])*state.specs[event['instrument_id']]['lot_size'],'Submitted native lot')
            active=pd.Timestamp(event['active_at']);check(active==clock+pd.Timedelta(minutes=config['execution_delay_bars']),'Order activation clock differs')
        elif typ=='ORDER_ACCEPTED':
            check(event['order_id'] in orders,'Acceptance before submission');accepted[event['order_id']]=sequence
        elif typ=='ORDER_CANCELLED':cancelled[event['order_id']]=sequence
        elif typ in ('ORDER_FILLED','ORDER_PARTIALLY_FILLED'):filled_events[event['order_id']].append(event)
        elif typ=='LIQUIDATION':liq_events[(clock,event['instrument_id'])].append(event)
    fee_events=[r for r in event_rows if r['type']=='FEE']
    check(len(fee_events)==len(fills),'Fee event count differs')
    for event,fill in zip(fee_events,fills):
        check(pd.Timestamp(event['timestamp'])==pd.Timestamp(fill['timestamp']) and event['instrument_id']==fill['instrument_id'],'Fee event identity differs')
        close(event['amount'],-fill['fee'],'Fee event cash amount')
    funding_events=[r for r in event_rows if r['type']=='FUNDING_PAYMENT']
    check(len(funding_events)==len(funded),'Funding event count differs')
    for event,payment in zip(funding_events,funded):
        check(pd.Timestamp(event['timestamp'])==pd.Timestamp(payment['timestamp']) and event['instrument_id']==payment['instrument_id'],'Funding cash event identity differs')
        close(event['amount'],payment['funding_payment'],'Funding event cash amount')
        check(event['rate']==payment['funding_rate'],'Funding event rate differs')
    order_filled=defaultdict(float);consumed_payments=set();preopen={};reconstructed_equity=[];reconstructed_exposure=[]
    def liquidation(clock,remaining):
        candidates=state.liquidation_ids()
        for i in candidates:
            check(remaining and remaining[0]['instrument_id']==i and remaining[0]['exit_reason']=='liquidation','Missing/incorrect venue-local forced liquidation')
            r=remaining.pop(0);quantity=abs(state.q[i]);side=-1 if state.q[i]>0 else 1
            close(r['quantity'],quantity,'Forced full native close');check(r['side']==side,'Wrong liquidation side')
            check(r['reference_price']==state.mark[i],'Liquidation reference differs from source stage mark')
            close(r['price'],adverse(state.mark[i],side,state.specs[i],config),'Forced adverse tick price')
            state.fill(r)
            events=liq_events[(clock,i)];check(events,'Missing liquidation event');event=events.pop(0)
            close(event['mark_price'],r['reference_price'],'Liquidation event mark');close(event['execution_price'],r['price'],'Liquidation event price');close(event['cash_after'],state.cash[state.specs[i]['exchange']],'Liquidation local cash')
    for number,clock in enumerate(expected_clock):
        remaining=list(fg.get(clock,[]));elapsed=(clock-begin).total_seconds()/60;aligned=elapsed==int(elapsed)
        if aligned and elapsed>0:
            index=int(elapsed)-1
            for i in ids:state.mark[i]=float(arrays[i]['mark_price'][index])
        liquidation(clock,remaining)
        for event in sg.get(clock,[]):state.mark[event['instrument_id']]=float(event['mark_price'])
        liquidation(clock,remaining)
        for event in sg.get(clock,[]):
            key=(clock,event['instrument_id']);payment=pg.get(key)
            state.funding_event(event,payment)
            if payment is not None:consumed_payments.add(key)
        liquidation(clock,remaining)
        preopen[clock]=dict(state.q)
        if aligned and clock<stop:
            index=int(elapsed)
            for i in ids:state.mark[i]=float(arrays[i]['mark_open'][index])
            liquidation(clock,remaining)
            capacity_used=defaultdict(float)
            for r in list(remaining):
                check(r['exit_reason']=='strategy','Unhealthy or misplaced forced fill')
                i=r['instrument_id'];spec=state.specs[i];oid=r['order_id'];check(oid in orders and oid in accepted,'Fill lacks immutable accepted order')
                order=orders[oid];check(order['instrument_id']==i and int(order['side'])==r['side'],'Fill/order target differs')
                check(pd.Timestamp(order['active_at'])<=clock and pd.Timestamp(order['timestamp'])<=clock,'Fill precedes submission/activation')
                check(filled_events[oid],'Missing ordered fill event')
                event_sequence=filled_events[oid][0]['_sequence']
                check(accepted[oid]<event_sequence and orders[oid]['_sequence']<event_sequence and (oid not in cancelled or cancelled[oid]>event_sequence),'Fill follows cancellation or precedes ordered acceptance')
                reference=float(arrays[i]['open'][index]);check(r['reference_price']==reference,'Execution reference is not actual minute open')
                check(np.isclose(r['price'],adverse(reference,r['side'],spec,config),rtol=1e-12,atol=1e-12),'Execution adverse tick price differs')
                cap=(float(arrays[i]['volume'][index-1]) if index>0 else 0.)*config['participation']
                available_capacity=max(0.,cap-capacity_used[i])
                remaining_order=order['quantity']-order_filled[oid]
                expected_quantity=math.floor((min(remaining_order,available_capacity)+spec['lot_size']*1e-9)/spec['lot_size'])*spec['lot_size']
                if order['reduce_only']:expected_quantity=min(expected_quantity,abs(state.q[i]))
                close(r['quantity'],expected_quantity,'Exact remaining-order/prior-volume native fill quantity')
                capacity_used[i]+=r['quantity']
                check(capacity_used[i]<=cap+max(1e-8,cap*1e-12),'Fill exceeds prior completed volume capacity')
                check(abs(r['quantity']/spec['lot_size']-round(r['quantity']/spec['lot_size']))<1e-6 and r['quantity']>=spec['min_quantity']-EPS,'Fill violates native lot/minimum')
                order_filled[oid]+=r['quantity'];check(order_filled[oid]<=order['quantity']+max(1e-8,order['quantity']*1e-12),'Immutable order quantity exceeded')
                if order['reduce_only']:
                    check(state.q[i]*r['side']<0 and r['quantity']<=abs(state.q[i])+EPS,'Reduce-only fill opened or flipped inventory')
                else:check(r['quantity']*r['price']>=spec['min_notional']-EPS,'Opening fill below native minimum notional')
                events=filled_events[oid];check(events,'Missing order fill event');event=events.pop(0)
                check(pd.Timestamp(event['timestamp'])==clock,'Order fill event clock');close(event['quantity'],r['quantity'],'Order fill event quantity');close(event['price'],r['price'],'Order fill event price')
                # Close-only fills are admissible without new risk; opening risk is local to the wallet.
                old=state.q[i];new=old+r['side']*r['quantity']
                if not (old*r['side']<0 and abs(new)<=abs(old)+EPS):
                    a=state.aggregates();venue=spec['exchange'];eq=a[venue+'_equity']-r['side']*r['quantity']*(r['price']-state.mark[i])-r['fee'];gross=a[venue+'_gross_exposure']-abs(old)*state.mark[i]+abs(new)*state.mark[i]
                    check(eq>0 and gross<=eq*.5+EPS and abs(new)*state.mark[i]<=eq*.25+EPS,'Opening fill violates separate wallet margin/risk limits')
                state.fill(r);remaining.pop(0)
            liquidation(clock,remaining)
        check(not remaining,'Nonexecuted/misplaced fills left at source clock')
        a=state.aggregates();x=state.exposure()
        if number==0:
            check(not any(state.q.values()) and not state.fees,'Initial baseline unexpectedly traded')
            baseline=Replay(specs,config);a=baseline.aggregates();x=baseline.exposure()
        reconstructed_equity.append(a);reconstructed_exposure.append(x)
    check(consumed_payments==set(pg),'Extra actual funding payments')
    check(all(not v for v in filled_events.values()) and all(not v for v in liq_events.values()),'Unmatched fill/liquidation events')
    # Compare columns in bulk, avoiding a row-wise 127-column pandas loop.
    expected_eq=pd.DataFrame(reconstructed_equity)
    equity_columns=(set(expected_eq)|{'timestamp'})-{v+'_'+k for v in VENUES for k in ('gross_exposure','margin_used','available_margin')}
    check(set(equity)==equity_columns,'Equity schema differs')
    for k in expected_eq:
        if k in equity:close(equity[k].to_numpy(),expected_eq[k].to_numpy(),'Equity '+k)
    expected_x=pd.DataFrame(reconstructed_exposure)
    check(set(exposure)==set(expected_x)|{'timestamp'},'Exposure field identities differ')
    for k in expected_x:
        if k.startswith('mark_'):check(np.array_equal(exposure[k].to_numpy(),expected_x[k].to_numpy()),'Source mark observer differs: '+k)
        else:close(exposure[k].to_numpy(),expected_x[k].to_numpy(),'Exposure '+k)
    trades=tables['trades'];check(len(trades)==len(state.trade_rows),'Trade count differs from replay')
    for row,expected in zip(trades.to_dict('records'),state.trade_rows):
        for k,v in expected.items():
            if isinstance(v,(float,np.floating)):close(row[k],v,'Trade '+k)
            else:check(row[k]==v,'Trade identity '+k)
    positions=tables['positions'];expected_ids={i for i in ids if abs(state.q[i])>EPS}
    check(len(positions)==len(expected_ids) and (set(positions.instrument_id) if len(positions) else set())==expected_ids,'Final native open position set differs')
    for row in positions.to_dict('records'):
        i=row['instrument_id'];spec=state.specs[i]
        for k,v in dict(quantity=state.q[i],average_price=state.avg[i],mark_price=state.mark[i],unrealized_pnl=state.q[i]*(state.mark[i]-state.avg[i]),funding_pnl=state.fund[i],entry_fees=state.entryfee[i],collateral=state.alloc[i],maintenance_margin=abs(state.q[i])*state.mark[i]*spec['maintenance_rate']).items():close(row[k],v,'Open position '+k)
        check(row['exchange']==spec['exchange'] and row['symbol']==spec['symbol'] and pd.isna(row['liquidation_price']),'Cross open position identity/liquidation threshold')
    return state,preopen


def reference_metrics(equity,trades,fills):
    """Independent descriptive formulas for every exported base metric."""
    series=pd.Series(equity.equity.to_numpy(dtype=float),index=pd.DatetimeIndex(equity.timestamp).as_unit('ns'))
    initial,final=float(series.iloc[0]),float(series.iloc[-1]);elapsed=(series.index[-1]-series.index[0]).total_seconds();days=elapsed/86400
    ending=series.resample('D').last().ffill();previous=ending.shift(1);previous.iloc[0]=initial
    returns=ending/previous-1;returns[(previous<=0)|(ending<0)]=np.nan
    if len(series)==1 or (series.index[1:].normalize()!=series.index[0].normalize()).all():returns=returns.iloc[1:]
    returns=returns.dropna();std=float(returns.std(ddof=1)) if len(returns)>1 else np.nan
    downside=float(np.sqrt(np.mean(np.minimum(returns.to_numpy(),0)**2))) if len(returns) else np.nan
    def ratio(a,b):return a/b if b>0 else None
    growth=math.log(final/initial)*365*86400/elapsed if initial>0 and final>0 and elapsed>0 else None
    cagr=math.expm1(growth) if growth is not None and growth<709 else None
    drawdown=series/series.cummax()-1;drawdown[series.cummax()<=0]=np.nan
    peak_clock=series.index[0];trough_clock=peak_clock;trough=0.;active=False;longest=0.;recoveries=[]
    for clock,value in drawdown.items():
        if pd.isna(value):continue
        if value>=-1e-14:
            if active:longest=max(longest,(clock-peak_clock).total_seconds()/86400);recoveries.append((clock-trough_clock).total_seconds()/86400)
            peak_clock=clock;active=False;trough=0.
        else:
            active=True
            if value<trough:trough=value;trough_clock=clock
            longest=max(longest,(clock-peak_clock).total_seconds()/86400)
    out=dict(initial_equity=initial,final_equity=final,total_return=final/initial-1 if initial>0 else None,cagr=cagr,annualized_volatility=std*np.sqrt(365),sharpe=ratio(float(returns.mean())*np.sqrt(365),std),sortino=ratio(float(returns.mean())*np.sqrt(365),downside),elapsed_days=days,daily_return_count=len(returns),max_drawdown=float(-drawdown.min()),max_drawdown_duration_days=longest,max_recovery_days=max(recoveries) if recoveries else None,currently_underwater=active)
    out['calmar']=ratio(cagr,out['max_drawdown']) if cagr is not None else None
    last=equity.iloc[-1]
    out.update(trading_pnl=float(last.realized_pnl+last.unrealized_pnl),funding_pnl=float(last.funding_pnl),trading_fees=float(last.trading_fees),slippage_cost=float(last.slippage_cost),liquidation_fees=float(last.liquidation_fees),net_profit=final-initial,liquidation_count=int(trades.exit_reason.eq('liquidation').sum()) if 'exit_reason' in trades else None,average_turnover_per_day=last.turnover/days if days>0 else None,turnover=float(last.turnover),turnover_multiple=ratio(last.turnover,initial))
    weights=np.diff(series.index.asi8).astype(float)
    def weighted(values):return float(np.average(np.asarray(values,dtype=float)[:-1],weights=weights)) if weights.sum()>0 else None
    for key in ('gross_exposure','net_exposure','long_exposure','short_exposure','gross_leverage'):
        out['average_'+key]=weighted(equity[key]);out['max_'+key]=float(equity[key].max())
    out['exposure_time']=weighted((equity.gross_exposure>0).astype(float))
    out['average_net_leverage']=weighted(equity.net_exposure/equity.equity.replace(0,np.nan))
    pnl=trades.net_pnl.to_numpy(dtype=float) if 'net_pnl' in trades else np.array([]);wins=pnl[pnl>0];losses=pnl[pnl<0]
    out.update(trade_count=len(pnl),win_rate=len(wins)/len(pnl) if len(pnl) else None,profit_factor=ratio(float(wins.sum()),float(-losses.sum())),expectancy=float(pnl.mean()) if len(pnl) else None,average_win=float(wins.mean()) if len(wins) else None,average_loss=float(losses.mean()) if len(losses) else None,payoff_ratio=ratio(float(wins.mean()),float(-losses.mean())) if len(wins) and len(losses) else None,trades_per_day=len(pnl)/days if days>0 else None,pnl_per_trade=float(pnl.mean()) if len(pnl) else None,pnl_per_unit_turnover=ratio(final-initial,out['turnover']),average_holding_seconds=float(trades.holding_seconds.mean()) if 'holding_seconds' in trades and len(trades) else None,median_holding_seconds=float(trades.holding_seconds.median()) if 'holding_seconds' in trades and len(trades) else None,net_winning_trade_profit=float(wins.sum()),net_losing_trade_loss=float(-losses.sum()))
    gp=float(trades.gross_pnl.clip(lower=0).sum()) if 'gross_pnl' in trades else 0.
    out.update(gross_profit=gp if 'gross_pnl' in trades else None,gross_loss=float(-trades.gross_pnl.clip(upper=0).sum()) if 'gross_pnl' in trades else None,fees_as_fraction_gross_profit=ratio(out['trading_fees'],gp),slippage_as_fraction_gross_profit=ratio(out['slippage_cost'],gp))
    if len(fills):
        notionals=abs(fills.quantity*fills.price);maker=fills.liquidity_type.eq('maker');taker=fills.liquidity_type.eq('taker')
        out.update(fill_count=len(fills),maker_ratio=float(maker.mean()),taker_ratio=float(taker.mean()),maker_notional_ratio=ratio(float(notionals[maker].sum()),float(notionals.sum())),maker_fees=float(fills.loc[maker,'fee'].sum()),taker_fees=float(fills.loc[taker,'fee'].sum()))
    else:out.update(fill_count=0,maker_ratio=None,taker_ratio=None,maker_notional_ratio=None,maker_fees=None,taker_fees=None)
    out['symbol_attribution']=trades.groupby('symbol').net_pnl.sum().to_dict() if {'symbol','net_pnl'}<=set(trades) else {}
    out['exchange_attribution']=trades.groupby('exchange').net_pnl.sum().to_dict() if {'exchange','net_pnl'}<=set(trades) else {}
    out['alpha']=out['beta']=None
    return {k:(float(v) if np.isfinite(v) else None) if isinstance(v,(float,np.floating)) else v for k,v in out.items()}


def phase_statistics(equity,trades,fills,positions,state,matched):
    values=equity.equity.to_numpy(dtype=float);initial=values[0];final=values[-1]
    daily=endpoint_returns(equity).dropna();std=float(daily.std(ddof=1));sharpe=float(daily.mean()/std*np.sqrt(365)) if std>0 else None
    fee=sum(abs(state.q[i])*state.mark[i]*state.specs[i]['taker_bps']/10000 for i in state.ids)
    slip=sum(abs(state.q[i])*state.mark[i]*state.config['slippage_bps']/10000 for i in state.ids)
    drawdown=1-values/np.maximum.accumulate(values)
    result=dict(initial_equity=float(initial),final_equity=float(final),total_return=float(final/initial-1),max_drawdown=float(np.nanmax(drawdown)),funding_pnl=state.funding,trading_pnl=state.realized+sum(state.q[i]*(state.mark[i]-state.avg[i]) for i in state.ids),trading_fees=state.fees,slippage_cost=state.slip,liquidation_fees=state.liqfees,net_profit=float(final-initial),turnover=state.turnover,fill_count=len(fills),trade_count=len(trades),sharpe=sharpe,daily_return_count=len(daily),open_position_count=len(positions),matched_entry_count=len(matched),matched_pairs=sorted({row['symbol'] for row in matched}),indicative_exit_fee_reserve=fee,indicative_exit_slippage_reserve=slip,indicative_exit_reserve_total=fee+slip,return_after_indicative_exit_reserve=(final-fee-slip)/100000.-1,joint_account=True,separate_venue_wallets=True)
    base=reference_metrics(equity,trades,fills);base.update(result);return base


def verify_csv(path,frame):
    if not len(frame.columns):check(Path(path).read_text().strip()=='','Empty CSV differs');return
    csv=pd.read_csv(path)
    check(list(csv)==list(frame) and len(csv)==len(frame),'CSV/Parquet schema or count mismatch: '+str(path))
    for col in frame:
        source=frame[col]
        if isinstance(source.dtype,pd.DatetimeTZDtype):check(np.array_equal(pd.to_datetime(csv[col],utc=True,format='mixed').dt.as_unit('ns').array.asi8,clocks(source)),'CSV timestamp differs')
        elif pd.api.types.is_numeric_dtype(source) and not pd.api.types.is_bool_dtype(source):close(csv[col].to_numpy(),source.to_numpy(),'CSV '+col)
        elif col=='targets':
            # Python dictionary text is the CSV rendering, not a numerical source of truth.
            check(csv[col].tolist()==source.map(str).tolist(),'CSV targets differ')
        else:check(csv[col].fillna('').astype(str).tolist()==source.fillna('').astype(str).tolist(),'CSV field differs: '+col)


def contributions(state):
    rows=[]
    for symbol in SYMBOLS:
        for venue in VENUES:
            i=iid(venue,symbol);net=state.leg_net[i]+state.q[i]*(state.mark[i]-state.avg[i])
            rows.append(dict(symbol=venue+'_'+symbol,instrument_id=i,net_pnl=net,fill_count=state.leg_fills[i],open_quantity=state.q[i],funding_cash=state.leg_fund[i],venue=venue,pair=symbol))
    pairs=[]
    for symbol in SYMBOLS:
        selected=[r for r in rows if r['pair']==symbol]
        pairs.append(dict(pair=symbol,net_pnl=sum(r['net_pnl'] for r in selected),funding_cash=sum(r['funding_cash'] for r in selected),fill_count=sum(r['fill_count'] for r in selected)))
    return rows,pairs


def verify_matched(path,preopen,orders,diagnostics):
    frame=pd.read_parquet(path/'matched_entries.parquet');rows=frame.to_dict('records')
    submitted=[r for r in diagnostics['events'] if r['type']=='PAIR_SUBMITTED']
    completed=[r for r in diagnostics['events'] if r['type']=='PAIR_COMPLETE']
    check(len(completed)==len(rows),'Matched entries and completion diagnostics differ')
    for row,event in zip(rows,completed):
        clock=pd.Timestamp(row['timestamp']);symbol=row['symbol'];targets=row['targets']
        check(symbol in SYMBOLS and clock in preopen and set(targets)=={iid(v,symbol) for v in VENUES},'Matched entry identity/clock differs')
        check(pd.Timestamp(event['timestamp'])==clock and event['symbol']==symbol and event['targets']==targets,'Completion diagnostic differs from matched entry')
        b,y=iid('binance',symbol),iid('bybit',symbol)
        check(targets[b]*targets[y]<0 and targets[b]==-targets[y],'Native pair completion not matched')
        for i,q in targets.items():close(preopen[clock][i],q,'Actual post-fill completion native quantity')
        candidates=[s for s in submitted if s['symbol']==symbol and pd.Timestamp(s['timestamp'])<=clock and s['targets']==targets]
        check(candidates,'Completion without submitted fixed targets')
        event=max(candidates,key=lambda s:pd.Timestamp(s['timestamp']))
        check(clock<=pd.Timestamp(event['deadline']),'Completed entry after immutable deadline')
    check(diagnostics['matched_entries']==[dict(timestamp=pd.Timestamp(r['timestamp']).isoformat(),symbol=r['symbol'],targets=r['targets']) for r in rows],'JSON/Parquet matched entries differ')
    return rows


def verify_phase(binance,bybit,out,phase,lock):
    name,begin,stop,stress,valuation=phase;path=out/'trials'/name
    outputs={n:sha(path/n) for n in OUTPUTS}
    parameters=expected_parameters(out,phase);completion=read(path/'completion.json')
    check(completion==dict(parameters=parameters,outputs_sha256=outputs),'Phase completion/output seal differs')
    metadata=read(path/'metadata.json');specs=expected_specs(binance,bybit,stress);cfg=configuration(stress)
    check(metadata['parameters']==parameters and metadata['engine']==cfg and metadata['instruments']==specs,'Phase parameters/config/catalog differs')
    check(metadata['strategy']=='CrossVenueCarry' and metadata['strategy_version']=='prospective-cross-venue-funding-differential-1','Coordinator class/version differs')
    check(metadata['source_sha256']=={p.removeprefix('aster/'):h for p,h in lock['sources'].items() if p.startswith('aster/')},'Core source hashes differ')
    commit=metadata['git_commit'];check(isinstance(commit,str) and re.fullmatch('[a-f0-9]{40}',commit),'Missing full execution Git identity')
    check(subprocess.run(['git','merge-base','--is-ancestor',ANCHOR,commit],cwd=REPO,capture_output=True).returncode==0,'Execution commit does not descend from reviewed source')
    manifest=dict(source_lock=lock,valuation=valuation,funding_boundary='actual sourced begin<=timestamp<=stop; Bybit mark valuation explicitly approximate')
    check(metadata['source_manifest']==manifest and read(path/'source_manifest.json')==manifest,'Phase source/valuation manifest differs')
    check(metadata['start']==str(begin) and metadata['end']==str(stop) and metadata['timeframes_seconds']==[60],'Executed bounds/timeframe differ')
    check(metadata['software']=='aster' and metadata['open_positions_marked'] is True and metadata['terminal_forced_close'] is False,'Software/terminal policy differs')
    version_file=(out/'executed_source/aster/__init__.py').read_text()
    check(re.search(r"__version__\s*=\s*['\"]"+re.escape(metadata['version'])+r"['\"]",version_file),'Executed package version differs')
    check(metadata['python']==lock['runtime']['python'] and metadata['dependencies']=={p:lock['runtime'][p] for p in ('numpy','pandas','pyarrow','plotly')},'Executed runtime/dependencies differ')
    tables={n:pd.read_parquet(path/(n+'.parquet')) for n in LEDGERS}
    for n,frame in tables.items():verify_csv(path/(n+'.csv'),frame)
    exposure=pd.read_parquet(path/'exposure.parquet');verify_csv(path/'exposure.csv',exposure)
    for n in ('unmatched','matched_entries'):verify_csv(path/(n+'.csv'),pd.read_parquet(path/(n+'.parquet')))
    bars,funding=source_inputs(binance,bybit,phase)
    check(metadata['data_sha256']==csv_hash(list(bars.values())) and metadata['funding_sha256']==csv_hash([funding]),'Phase normalized input serialization hashes differ')
    state,preopen=reconstruct(tables,exposure,bars,funding,specs,cfg,begin,stop)
    diagnostics=read(path/'strategy_diagnostics.json')
    matched=verify_matched(path,preopen,{},diagnostics)
    actual_legs=pd.read_csv(path/'leg_contributions.csv').to_dict('records');actual_pairs=pd.read_csv(path/'pair_contributions.csv').to_dict('records');legs,pairs=contributions(state)
    compare(actual_legs,legs,'All sixteen native leg contributions');compare(actual_pairs,pairs,'All eight pair contributions')
    close(sum(r['net_pnl'] for r in legs),tables['equity'].equity.iloc[-1]-100000,'Native leg net P&L conservation')
    quality=read(path/'quality.json');check(not quality['errors'] and metadata['data_quality']==quality,'Source quality errors/identity differ')
    score=read(path/'metrics.json');statistics=phase_statistics(tables['equity'],tables['trades'],tables['fills'],tables['positions'],state,matched)
    check(set(score)==set(statistics)|{'liquidation_event_count','runtime_seconds','peak_rss_mib_process'},'Metric schema differs')
    for k,v in statistics.items():
        if isinstance(v,float) or v is None:close(score[k],v,'Metric '+k)
        else:compare(score[k],v,'Metric '+k)
    events=tables['events'];liq=int(events.type.eq('LIQUIDATION').sum()) if len(events) else 0
    check(score['liquidation_event_count']==liq,'Actual liquidation event metric differs')
    check(math.isfinite(score['runtime_seconds']) and score['runtime_seconds']>=0 and score['peak_rss_mib_process']>0,'Invalid runtime diagnostic')
    check({n:sha(path/n) for n in OUTPUTS}==outputs,'Outputs changed during financial audit')
    record=dict(outputs_sha256=outputs,equity_snapshots=len(tables['equity']),fills=len(tables['fills']),closed_trades=len(tables['trades']),funding_cash_events=len(tables['funding']),open_positions=len(tables['positions']),liquidation_events=liq,matched_entries=len(matched),trajectory_reconstruction_passed=True)
    return record,score,tables['equity'],legs,pairs


def rebuild_summary(out,records):
    scores={p[0]:records[p[0]][1] for p in PHASES}
    validation=float(np.prod([1+scores[f'validation{k}']['total_return'] for k in (1,2,3)])-1)
    reserve_validation=float(np.prod([1+scores[f'validation{k}']['return_after_indicative_exit_reserve'] for k in (1,2,3)])-1)
    base=scores['evaluation'];frame=records['evaluation'][2];series=frame.set_index('timestamp').equity
    points=[float(series.asof(EVAL+pd.DateOffset(months=k))) for k in range(4)]
    months=[points[k+1]/points[k]-1 for k in range(3)]
    participants=set(base['matched_pairs'])
    gates=dict(positive_compounded_validation=validation>0,positive_validation_after_exit_reserve=reserve_validation>0,two_positive_anchored_months=sum(r>0 for r in months)>=2,daily_sharpe_at_least_half=base['sharpe'] is not None and base['sharpe']>=.5,minute_drawdown_at_most_twenty_percent=base['max_drawdown']<=.2,no_liquidation_all_seven_runs=sum(s['liquidation_event_count'] for s in scores.values())==0,four_matched_pairs_including_both_doge_and_pepe=len(participants)>=4 and {'DOGEUSDT','PEPEUSDT'}<=participants)
    for n in ('evaluation','evaluation_stress','evaluation_alternative','evaluation_alternative_stress'):
        gates['positive_'+n]=scores[n]['total_return']>0;gates['positive_'+n+'_after_exit_reserve']=scores[n]['return_after_indicative_exit_reserve']>0
    return dict(family=FAMILY,candidate_count_cumulative=26,research_status='exploratory reused year; no untouched holdout',passes_hurdles=all(gates.values()),gates=gates,failed_gates=[k for k,v in gates.items() if not v],validation_compounded_return=validation,validation_after_exit_reserve=reserve_validation,scores=scores,anchored_month_returns=months,actual_matched_pairs=sorted(participants),evaluation_leg_contributions=records['evaluation'][3],evaluation_pair_contributions=records['evaluation'][4],conditional_interval=interval(frame),full_resolution_evaluation_equity_sha256=sha(out/'trials/evaluation/equity.parquet'),source_lock_sha256=sha(out/'source_lock.json'),features_sha256=sha(out/'features.parquet'),publication_status='UNPUBLISHED: separate independent seven-phase reconstruction receipt required')


def verify(binance,bybit,out):
    auditor_sha256=sha(__file__)
    binance,bybit,out=Path(binance),Path(bybit),Path(out);lock=packet_guard(out)
    check({p.name for p in (out/'trials').iterdir()}=={p[0] for p in PHASES},'Require exactly seven trial directories')
    records={}
    for phase in PHASES:
        print('Auditing fixed phase',phase[0],flush=True)
        records[phase[0]]=verify_phase(binance,bybit,out,phase,lock)
    compare(read(out/'summary.json'),rebuild_summary(out,records),'Independent complete summary')
    packet_guard(out)
    check(sha(__file__)==auditor_sha256,'Auditor source changed during reconstruction')
    return dict(complete=True,errors=[],expected_trials=7,completed_trials=7,output_files_checked=175,trials={n:r[0] for n,r in records.items()},source_lock_sha256=sha(out/'source_lock.json'),features_sha256=sha(out/'features.parquet'),feature_receipt_sha256=sha(out/'feature_receipt.json'),summary_sha256=sha(out/'summary.json'),source_anchor=ANCHOR,input_anchor=INPUT_ANCHOR,source_files_checked=len(lock['sources']),input_files_checked=len(lock['inputs']),auditor_sha256=auditor_sha256,source_unchanged_during_audit=True,auditor_source_unchanged=True,trajectory_reconstruction_passed=True,summary_reconstruction_passed=True,execution_fill_reconstruction_passed=True,separate_wallet_reconstruction_passed=True,strategy_policy_reconstruction_passed=False,scope='Seven fixed simulations: recorded executable fills and source-based financial/statistical reconstruction. This is not a full generic strategy decision or omitted-order proof. Separate causal feature and cohort-specific no-admission certificates required for publication.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--binance',default='data_cache/minute-perpetual-1y');p.add_argument('--bybit',default='data_cache/minute-bybit-1y');p.add_argument('--out',default='results/cross-venue-funding-1y-v1');p.add_argument('--certificate',default='audit/cross_venue_output_evidence.json');args=p.parse_args()
    certificate=verify(args.binance,args.bybit,args.out);path=Path(args.certificate);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(certificate,indent=2,sort_keys=True,allow_nan=False)+'\n');print(json.dumps({'complete':True,'trials':7,'outputs':175,'certificate':str(path)}))

if __name__=='__main__':main()
