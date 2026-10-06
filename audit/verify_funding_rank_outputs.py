"""Independent five-phase joint-wallet trajectory reconstruction.

No imports from the engine, portfolio, strategy, signals or frozen runner.
Arithmetic adapted from the independently audited cross-venue verifier;
no strategy/runner/core imports and no historical evaluation on import.
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
SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
VENUES=('binance',)
FAMILY='joint_cross_sectional_funding_rank'
START=pd.Timestamp('2025-10-05',tz='UTC');VALID=pd.Timestamp('2026-04-05',tz='UTC');EVAL=pd.Timestamp('2026-07-05',tz='UTC');END=pd.Timestamp('2026-10-05',tz='UTC')
PHASES=[(f'validation{k+1}',VALID+pd.DateOffset(months=k),VALID+pd.DateOffset(months=k+1),False) for k in range(3)]+[('evaluation',EVAL,END,False),('evaluation_stress',EVAL,END,True)]
LEDGERS=('equity','fills','trades','funding','events','positions')
OUTPUTS=tuple([f'{n}.{e}' for n in LEDGERS for e in ('csv','parquet')]+['metadata.json','metrics.json','source_manifest.json','quality.json','exposure.csv','exposure.parquet','leg_contributions.csv','strategy_diagnostics.json','completed_baskets.json','proposal_ledger.json','rejections.json','terminal_orders.json','daily_returns.csv'])
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
        a=self.aggregates();row={k:a[k] for k in ('cash','equity','gross_exposure','net_exposure','available_margin','margin_used','maintenance_margin')}
        row['live_order_count']=getattr(self,'live_order_count',0)
        for key in ('cash','equity','gross_exposure','available_margin','margin_used'):
            row['binance_'+key]=a['binance_'+key]
        row['binance_maintenance_margin']=a['maintenance_margin']
        for symbol in SYMBOLS:
            i=iid('binance',symbol);q=self.q[i];mark=self.mark[i]
            for key,value in [('quantity',q),('mark',mark),('unrealized',q*(mark-self.avg[i])),('entry_collateral_field',self.alloc[i]),('signed_notional',q*mark),('current_mark_initial_margin',abs(q)*mark)]:row[key+'_'+symbol]=value
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
    check(pd.DatetimeIndex(exposure.timestamp).as_unit('ns').equals(expected_clock) and len(exposure.columns)==len(state.exposure())+1,'Observer clock/63-field schema differs')
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
    live_events=defaultdict(list)
    for event in event_rows:
        if event['type'] in ('ORDER_ACCEPTED','ORDER_FILLED','ORDER_REJECTED','ORDER_CANCELLED') and not (event['type']=='ORDER_CANCELLED' and event.get('reason')=='end_of_data'):
            live_events[pd.Timestamp(event['timestamp'])].append(event)
    live=set()
    for number,clock in enumerate(expected_clock):
        for event in live_events.get(clock,[]):
            if event['type']=='ORDER_ACCEPTED':live.add(event['order_id'])
            else:live.discard(event['order_id'])
        state.live_order_count=len(live)
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
        if not hasattr(state,'preopen_account'):state.preopen_account={}
        state.preopen_account[clock]=state.aggregates()
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


def configuration(stress):
    return dict(initial_balances={'binance':100000.},margin_mode='cross',leverage=1,
        max_gross_leverage=.5,max_position_pct=.25,fill_model='volume_aware',
        participation=.025 if stress else .05,slippage_bps=16 if stress else 8,
        slippage_model='fixed',spread_bps=2.,impact_bps=10.,latency_ms=0,
        execution_delay_bars=int(stress),seed=42,funding_enabled=True,record_every=1)


def committed_file(commit,path):
    check(isinstance(commit,str) and re.fullmatch('[a-f0-9]{40}',commit),'Full Git anchor required')
    return subprocess.run(['git','show',commit+':'+path],cwd=REPO,capture_output=True,check=True).stdout


def packet_guard(out,source_anchor,input_anchor):
    out=Path(out)
    receipts={}
    for name in ('source_lock.json','input_verification.json','preregistration.json'):
        original=committed_file(input_anchor,'docs/funding_rank_preregistration/'+name)
        current=(out/name if name!='preregistration.json' else REPO/'docs/funding_rank_preregistration'/name).read_bytes()
        check(current==original,'Pre-feature committed receipt changed: '+name)
        receipts[name]=json.loads(original)
    lock=receipts['source_lock.json'];prereg=receipts['preregistration.json']
    check(prereg['source_commit']==source_anchor and prereg['proposed_candidate_number']==27,'Candidate/source preregistration differs')
    check(prereg['historical_features_exist'] is False and prereg['trial_directory_exists'] is False,'Not a pre-outcome input freeze')
    check(prereg['source_lock_sha256']==sha(out/'source_lock.json') and prereg['input_verification_sha256']==sha(out/'input_verification.json'),'Preregistration evidence SHA differs')
    check(prereg['source_files']==len(lock['sources']) and prereg['input_files']==len(lock['inputs']),'Preregistered exact file counts differ')
    check(lock['family']==FAMILY and lock['candidate_count_cumulative']==27,'Locked family/count differs')
    check(lock['phases']==[[n,str(b),str(e),s] for n,b,e,s in PHASES],'Locked five-phase dates differ')
    check(lock['input_verification']==receipts['input_verification.json'] and len(lock['input_verification'])==8,'Locked source verification differs')
    core=subprocess.run(['git','ls-tree','-r','--name-only',source_anchor,'--','aster'],cwd=REPO,capture_output=True,check=True,text=True).stdout.splitlines()
    expected={p for p in core if p.endswith('.py')}|{
        'examples/funding_rank/'+n for n in ('run.py','signals.py','strategy.py','proposed_protocol.md')}
    expected|={'examples/cross_venue/signals.py','examples/minute_research/download.py','examples/minute_research/downloadcarry.py'}
    check(set(lock['sources'])==expected,'Locked transitive source graph differs')
    for name,digest in lock['sources'].items():
        check(hashlib.sha256(committed_file(source_anchor,name)).hexdigest()==digest,'Reviewed source anchor differs: '+name)
        check(sha(REPO/name)==digest and sha(out/'executed_source'/name)==digest,'Executed/source archive drift: '+name)
    for path,digest in lock['inputs'].items():check(sha(path)==digest,'Raw/normalized input drift: '+path)
    check(lock['runtime']=={'python':sys.version,**{n:importlib.metadata.version(n) for n in ('numpy','pandas','pyarrow','scipy','plotly')}},'Runtime drift')
    return lock


def verify_completed_baskets(completed,diagnostics,preopen,tables,begin,stop):
    """Verify actual quantities, original targets and completion-fill deadlines.

    This is completion evidence, not a full replay of omitted strategy intents.
    A separate causal-policy verifier must examine ranks and admission decisions.
    """
    transactions={}
    for row in diagnostics['events']:
        if row['type']=='TARGET_SUBMITTED' and row['transition']=='ENTERING':
            check(row['generation'] not in transactions,'Duplicate entry generation')
            transactions[row['generation']]=row
    participants=set();generations=set();fills=tables['fills']
    for row in completed:
        gen=row['generation'];check(gen in transactions and gen not in generations,'Missing/repeated actual entry generation')
        tx=transactions[gen];targets=row['targets'];proposal=row['proposal']
        check(targets==tx['targets'] and set(targets)=={iid('binance',s) for s in SYMBOLS},'Frozen completed targets differ')
        symbols=proposal['longs']+proposal['shorts']
        check(len(symbols)==4 and len(set(symbols))==4 and set(symbols)<=set(SYMBOLS),'Invalid completed membership')
        observed=pd.Timestamp(row['observed_completed_at']);actual=pd.Timestamp(row['completed_at'])
        check(begin<=actual<=observed<stop and observed in preopen,'Completion clocks unavailable')
        chosen=fills.loc[fills.order_id.isin(tx['order_ids'])]
        check(len(chosen)>0 and actual==chosen.timestamp.max() and pd.Timestamp(row['timestamp'])==actual,'Actual completion is not last actual entry fill')
        check(actual<=pd.Timestamp(tx['deadline']),'Completed after immutable deadline')
        for s in SYMBOLS:
            i=iid('binance',s);q=targets[i]
            close(preopen[observed][i],q,'Observed actual completed native quantity')
            close(chosen.loc[chosen.instrument_id.eq(i),'quantity'].mul(chosen.loc[chosen.instrument_id.eq(i),'side']).sum(),q,'Actual completed entry-fill native quantity')
            check((q>0 if s in proposal['longs'] else q<0 if s in proposal['shorts'] else q==0),'Completed native orientation differs')
        participants.update(symbols);generations.add(gen)
    return sorted(participants),len(generations)


def verify_phase(cache,out,phase,lock,input_anchor):
    name,begin,stop,stress=phase;path=out/'trials'/name
    sealed={n:sha(path/n) for n in OUTPUTS}
    parameters=dict(family=FAMILY,phase=name,begin=str(begin),stop=str(stop),stress=stress,
        source_lock_sha256=sha(out/'source_lock.json'),features_sha256=sha(out/'features.parquet'),
        feature_receipt_sha256=sha(out/'feature_receipt.json'),research_status='exploratory reused year; candidate27')
    check(read(path/'completion.json')==dict(parameters=parameters,outputs_sha256=sealed),'Completed phase seal differs')
    specs=read(cache/'instruments.json');by_id={s['id']:dict(s,maker_bps=10 if stress else 5,taker_bps=10 if stress else 5) for s in specs}
    check(set(by_id)=={iid('binance',s) for s in SYMBOLS},'Native source catalog differs')
    specs=[by_id[iid('binance',s)] for s in SYMBOLS];cfg=configuration(stress)
    meta=read(path/'metadata.json')
    check(meta['parameters']==parameters and meta['engine']==cfg and meta['instruments']==specs,'Executed metadata/config/native catalog differs')
    check(meta['strategy']=='FundingRankPortfolio' and meta['strategy_version']=='prospective-weekly-funding-rank-1','Strategy class/version differs')
    check(meta['source_sha256']=={p.removeprefix('aster/'):h for p,h in lock['sources'].items() if p.startswith('aster/')},'Core source metadata differs')
    check(subprocess.run(['git','merge-base','--is-ancestor',input_anchor,meta['git_commit']],cwd=REPO,capture_output=True).returncode==0,'Execution precedes preregistration Git anchor')
    check(meta['start']==str(begin) and meta['end']==str(stop) and meta['timeframes_seconds']==[60],'Execution bounds/timeframe differ')
    check(meta['python']==lock['runtime']['python'] and meta['dependencies']=={n:lock['runtime'][n] for n in ('numpy','pandas','pyarrow','plotly')},'Executed runtime metadata differs')
    check(meta['software']=='aster' and meta['open_positions_marked'] is True and meta['terminal_forced_close'] is False,'Actual software/terminal accounting policy differs')
    manifest=dict(source_lock=lock,funding_boundary='actual sourced begin<=timestamp<=stop; predictor excludes END; original mark and native units',terminal_order_semantics='captured at final equity clock BEFORE automatic end_of_data cancellations')
    check(meta['source_manifest']==manifest and read(path/'source_manifest.json')==manifest,'Actual source manifest differs')
    tables={n:pd.read_parquet(path/(n+'.parquet')) for n in LEDGERS}
    quality=read(path/'quality.json')
    check(not quality['errors'] and meta['data_quality']==quality,'Executed source quality differs')
    for n,frame in tables.items():verify_csv(path/(n+'.csv'),frame)
    exposure=pd.read_parquet(path/'exposure.parquet');verify_csv(path/'exposure.csv',exposure)
    bars={};funds=[]
    for symbol in SYMBOLS:
        source=pd.read_parquet(cache/symbol/'bars.parquet');fund=pd.read_parquet(cache/symbol/'funding.parquet')
        i=iid('binance',symbol)
        check(source.instrument_id.eq(i).all() and source.duration_seconds.eq(60).all() and fund.instrument_id.eq(i).all(),'Wrong native minute/funding input')
        bars[i]=source.loc[source.timestamp.ge(begin)&source.timestamp.lt(stop)].reset_index(drop=True)
        funds.append(fund.loc[fund.timestamp.ge(begin)&fund.timestamp.le(stop)])
    funding=pd.concat(funds,ignore_index=True)
    check(meta['data_sha256']==csv_hash(list(bars.values())) and meta['funding_sha256']==csv_hash([funding]),'Serialized actual input hashes differ')
    state,preopen=reconstruct(tables,exposure,bars,funding,specs,cfg,begin,stop)
    diagnostics=read(path/'strategy_diagnostics.json');completed=read(path/'completed_baskets.json')
    participants,count=verify_completed_baskets(completed,diagnostics,preopen,tables,begin,stop)
    legs=[]
    for symbol in SYMBOLS:
        i=iid('binance',symbol)
        legs.append(dict(symbol=symbol,instrument_id=i,net_pnl=state.leg_net[i]+state.q[i]*(state.mark[i]-state.avg[i]),
            fill_count=state.leg_fills[i],open_quantity=state.q[i],funding_cash=state.leg_fund[i]))
    compare(pd.read_csv(path/'leg_contributions.csv').to_dict('records'),legs,'All eight leg contributions')
    check(read(path/'proposal_ledger.json')==[r for r in diagnostics['events'] if r['type'] in ('WEEKLY_PROPOSAL','PROPOSAL_REJECTED')],'Proposal export differs')
    check(read(path/'rejections.json')==[r for r in diagnostics['events'] if r['type'] in ('PROPOSAL_REJECTED','ADMISSION_REJECTED','ACCOUNT_RISK_BLOCKED')],'Refusal export differs')
    terminal=read(path/'terminal_orders.json');before=terminal['before_end_of_data_cancellation']
    check(terminal['after_run_live_orders']==[] and len(before)==exposure.live_order_count.iloc[-1],'Terminal order capture differs')
    check(all(o['status'] in ('accepted','partial') for o in before),'Invalid claimed live terminal order')
    for o in before:
        events=tables['events'];endcancel=events.loc[events.type.eq('ORDER_CANCELLED')&events.order_id.eq(o['id'])]
        check(len(endcancel)==1 and endcancel.reason.iloc[0]=='end_of_data' and endcancel.timestamp.iloc[0]==stop,'Unresolved terminal order lacks end_of_data cancellation')
    actual_terminal_quantities=[float(exposure[f'quantity_{s}'].iloc[-1]) for s in SYMBOLS]
    check(np.isfinite(actual_terminal_quantities).all(),'Nonfinite final observed native inventory')
    terminal_nonzero=sum(q!=0 for q in actual_terminal_quantities)
    terminal_flat=terminal_nonzero==0 and not before
    score=read(path/'metrics.json');base=reference_metrics(tables['equity'],tables['trades'],tables['fills'])
    daily=endpoint_returns(tables['equity']).dropna();std=float(daily.std(ddof=1))
    daily_export=pd.read_csv(path/'daily_returns.csv')
    check(list(daily_export)==['timestamp','return'] and len(daily_export)==len(daily),'Exported daily return grid/schema differs')
    check(pd.DatetimeIndex(pd.to_datetime(daily_export.timestamp,utc=True)).as_unit('ns').equals(daily.index.as_unit('ns')),'Exported daily return clocks differ')
    close(daily_export['return'].to_numpy(),daily.to_numpy(),'Exported daily return values')
    base.update(sharpe=float(daily.mean()/std*np.sqrt(365)) if np.isfinite(std) and std>0 else None,daily_return_count=len(daily))
    for k,v in base.items():compare(score[k],v,'Base metric '+k)
    fee=sum(abs(state.q[i])*state.mark[i]*state.specs[i]['taker_bps']/10000 for i in state.ids)
    slip=sum(abs(state.q[i])*state.mark[i]*cfg['slippage_bps']/10000 for i in state.ids)
    liq=int(tables['events'].type.eq('LIQUIDATION').sum()) if len(tables['events']) else 0
    extra=dict(indicative_exit_fee_reserve=fee,indicative_exit_slippage_reserve=slip,indicative_exit_reserve_total=fee+slip,
        return_after_indicative_exit_reserve=(float(tables['equity'].equity.iloc[-1])-fee-slip)/100000-1,
        liquidation_event_count=liq,open_position_count=len(tables['positions']),terminal_live_order_count=len(before),
        terminal_observed_nonzero_position_count=terminal_nonzero,
        terminal_flat_resolved=terminal_flat,completed_participants=participants,completed_basket_count=count,joint_account=True)
    for k,v in extra.items():compare(score[k],v,'Additional metric '+k)
    check(set(score)==set(base)|set(extra)|{'runtime_seconds','peak_rss_mib_process'},'Unverified metric fields')
    check({n:sha(path/n) for n in OUTPUTS}==sealed,'Evidence changed during replay')
    return dict(outputs_sha256=sealed,equity_snapshots=len(exposure),fills=len(tables['fills']),
        funding_cash_events=len(tables['funding']),closed_trades=len(tables['trades']),completed_baskets=count,
        participants=participants,liquidation_events=liq,terminal_flat_resolved=terminal_flat,
        trajectory_reconstruction_passed=True),score,tables['equity']


def summary_gates(records):
    scores={n:r[1] for n,r in records.items()};base=scores['evaluation'];stress=scores['evaluation_stress']
    validation=float(np.prod([1+scores[f'validation{k}']['total_return'] for k in (1,2,3)])-1)
    reserve=float(np.prod([1+scores[f'validation{k}']['return_after_indicative_exit_reserve'] for k in (1,2,3)])-1)
    series=records['evaluation'][2].set_index('timestamp').equity
    points=[float(series.asof(EVAL+pd.DateOffset(months=k))) for k in range(4)]
    months=[points[k+1]/points[k]-1 for k in range(3)];participants=set(base['completed_participants'])
    gates=dict(positive_compounded_validation=validation>0,positive_validation_after_exit_reserve=reserve>0,
        positive_evaluation=base['total_return']>0,positive_evaluation_after_exit_reserve=base['return_after_indicative_exit_reserve']>0,
        positive_stress=stress['total_return']>0,positive_stress_after_exit_reserve=stress['return_after_indicative_exit_reserve']>0,
        two_positive_anchored_months=sum(x>0 for x in months)>=2,daily_sharpe_at_least_half=base['sharpe'] is not None and base['sharpe']>=.5,
        minute_drawdown_at_most_twenty_percent=base['max_drawdown']<=.2,no_liquidation_all_five_runs=sum(s['liquidation_event_count'] for s in scores.values())==0,
        four_completed_assets=len(participants)>=4,completed_doge_participation='DOGEUSDT' in participants,
        completed_pepe_participation='PEPEUSDT' in participants,two_completed_entry_generations=base['completed_basket_count']>=2,
        actual_terminal_flat_all_five_runs=all(s['terminal_flat_resolved'] for s in scores.values()))
    return gates,validation,reserve,months


def verify(cache,out,source_anchor,input_anchor):
    cache,out=Path(cache),Path(out);own_sha=sha(__file__);lock=packet_guard(out,source_anchor,input_anchor)
    check({p.name for p in (out/'trials').iterdir()}=={p[0] for p in PHASES},'Unexpected/missing historical phases')
    feature_receipt=read(out/'feature_receipt.json')
    check(feature_receipt['source_lock_sha256']==sha(out/'source_lock.json') and feature_receipt['features_sha256']==sha(out/'features.parquet'),'Feature seal drift')
    records={p[0]:verify_phase(cache,out,p,lock,input_anchor) for p in PHASES}
    gates,validation,reserve,months=summary_gates(records);summary=read(out/'summary.json')
    check(summary['gates']==gates and summary['passes_hurdles']==all(gates.values()) and summary['failed_gates']==[k for k,v in gates.items() if not v],'Fifteen summary gates differ')
    close(summary['validation_compounded_return'],validation,'Validation compound');close(summary['validation_after_exit_reserve'],reserve,'Validation after reserve')
    compare(summary['anchored_month_returns'],months,'Anchored evaluation months')
    compare(summary['scores'],{n:r[1] for n,r in records.items()},'Five sealed scores')
    check(summary['family']==FAMILY and summary['candidate_count_cumulative']==27 and summary['research_status']=='exploratory reused year; no untouched holdout','Summary family/search/holdout claims differ')
    check(summary['completed_participants']==records['evaluation'][1]['completed_participants'] and summary['completed_basket_count']==records['evaluation'][1]['completed_basket_count'],'Summary completed participation differs')
    compare(summary['all_evaluation_leg_contributions'],pd.read_csv(out/'trials/evaluation/leg_contributions.csv').to_dict('records'),'Summary all eight legs')
    for field,path in [('source_lock_sha256',out/'source_lock.json'),('features_sha256',out/'features.parquet'),('feature_receipt_sha256',out/'feature_receipt.json'),('full_resolution_evaluation_equity_sha256',out/'trials/evaluation/equity.parquet')]:check(summary[field]==sha(path),'Summary evidence identity differs: '+field)
    values=endpoint_returns(records['evaluation'][2]).dropna().to_numpy();interval=summary['conditional_interval']
    check(len(values)>=7 and (values>-1).all() and np.isfinite(values).all() and interval['available'] is True,'Conditional interval input/status differs')
    n=len(values);rng=np.random.default_rng(42);starts=rng.integers(0,n,(10000,(n+6)//7))
    indices=((starts[:,:,None]+np.arange(7))%n).reshape(10000,-1)[:,:n]
    draws=np.expm1(np.log1p(values[indices]).sum(axis=1))
    check(interval['comparison_count']==27 and interval['tails']==[.05/54,1-.05/54],'Conditional comparison tails differ')
    close(interval['return_interval95'],np.quantile(draws,[.025,.975]),'Conditional 95 interval')
    close(interval['return_interval_bonferroni27'],np.quantile(draws,[.05/54,1-.05/54]),'Conditional 27-comparison interval')
    packet_guard(out,source_anchor,input_anchor);check(own_sha==sha(__file__),'Auditor changed during execution')
    return dict(complete=True,errors=[],source_anchor=source_anchor,input_anchor=input_anchor,auditor_sha256=own_sha,
        source_lock_sha256=sha(out/'source_lock.json'),features_sha256=sha(out/'features.parquet'),summary_sha256=sha(out/'summary.json'),
        phases={n:r[0] for n,r in records.items()},gates_reconstructed=True,
        scope='Independent native source minute/settlement cash, cross-margin trajectory, fills, collateral, ledgers, completed quantities, costs and fifteen gates. Full omitted policy intent/causal feature reconstruction are separate certificates.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',default='data_cache/minute-perpetual-1y');parser.add_argument('--out',default='results/funding-rank-1y-v1')
    parser.add_argument('--source-anchor',required=True);parser.add_argument('--input-anchor',required=True)
    parser.add_argument('--receipt',default='audit/funding_rank_output_evidence.json')
    args=parser.parse_args();check(not Path(args.receipt).exists(),'Preserve existing independent certificate')
    receipt=verify(args.cache,args.out,args.source_anchor,args.input_anchor)
    Path(args.receipt).parent.mkdir(parents=True,exist_ok=True)
    with Path(args.receipt).open('x') as stream:stream.write(json.dumps(receipt,indent=2,allow_nan=False)+'\n')
    print('Independent five-phase trajectory and fifteen-gate reconstruction passed.')


if __name__=='__main__':main()
