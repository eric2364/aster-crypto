"""Prospective one-wallet funding-ranked basket; no data loading or estimation."""
from fractions import Fraction
import math
import pandas as pd
from aster.backtest.execution import adverse_price, floor_step
from aster.backtest.models import Order
from aster.strategies.base import BaseStrategy

SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
LIVE=('accepted','partial')
EPS=1e-9
HOLD=pd.Timedelta(days=7)
COLD=pd.Timedelta(hours=24)


def native_quantity(budget,price,step):
    """Floor exact decimal inputs; never round a floating quantity over budget."""
    b,p,s=map(lambda x:Fraction(str(x)),(budget,price,step))
    if min(b,p,s)<=0:raise ValueError('Positive budget/price/lot required')
    units=(b/p)//s
    q=float(units*s)
    if Fraction(str(q))*p>b or q*float(price)>float(budget):q=float(max(0,units-1)*s)
    return q


class FundingRankPortfolio(BaseStrategy):
    version='prospective-weekly-funding-rank-1'
    def __init__(self,features,stop):
        clock=pd.DatetimeIndex(features.index)
        if clock.tz is None or clock.hasnans or clock.has_duplicates or not clock.is_monotonic_increasing:
            raise ValueError('Sorted unique timezone-aware feature availability index required')
        if not {f'{field}_{s}' for s in SYMBOLS for field in ('valid','yield','price')}<=set(features):
            raise ValueError('Require eight native price/valid/yield columns')
        self.features=features.copy();self.features.index=clock.tz_convert('UTC').as_unit('ns')
        self.stop=pd.Timestamp(stop)
        if self.stop.tzinfo is None:raise ValueError('Timezone-aware phase stop required')
        self.stop=self.stop.tz_convert('UTC')
        self.state='IDLE';self.active=None;self.proposal=None;self.transaction=None
        self.cleanup_orders={};self.cooldown_until=None;self.generation=0
        self.diagnostics=[];self.proposals=[];self.rejections=[];self.completed_baskets=[];self.matched_entries=self.completed_baskets
        self.unmatched=[];self.last_targets={};self.blocked=set()
        self.instruments=None;self._event_cursor=0;self._risk_latch=None;self.terminal_requested=False
        self.cleanup_deadline=None;self.cleanup_deadline_exceeded=False;self.abort_latched=False

    def _catalog(self,ctx):
        if self.instruments is not None:return
        by_symbol={s.symbol:s for s in ctx.instruments.values()}
        self.instruments={s:by_symbol['1000PEPEUSDT' if s=='PEPEUSDT' else s] for s in SYMBOLS}
        if len(ctx.instruments)!=8 or len(by_symbol)!=8 or any(s.exchange!='binance' or s.market_type!='perpetual' or s.contract_type!='linear' or s.multiplier!=1 or s.quote!='USDT' for s in self.instruments.values()):
            raise ValueError('Exactly eight native linear Binance USDT perpetuals required')
        if any(spec.id!=f'binance:perpetual:{spec.symbol}' or spec.base!=('1000PEPE' if label=='PEPEUSDT' else label[:-4]) for label,spec in self.instruments.items()):
            raise ValueError('Native contract identity/base mismatch')
        if set(ctx.portfolio.cash)!={'binance'} or ctx.portfolio.config.margin_mode!='cross' or ctx.portfolio.config.leverage!=1:
            raise ValueError('One actual Binance cross-margin leverage-one wallet required')
        self.by_id={s.id:s for s in self.instruments.values()}
        self.last_targets={iid:0. for iid in self.by_id}

    def _log(self,ctx,kind,**values):
        event=dict(timestamp=ctx.now,type=kind,generation=self.generation,**values)
        self.diagnostics.append(event)
        if kind in ('WEEKLY_PROPOSAL','PROPOSAL_REJECTED'):self.proposals.append(dict(event))
        if kind in ('PROPOSAL_REJECTED','ADMISSION_REJECTED','ACCOUNT_RISK_BLOCKED'):self.rejections.append(dict(event))

    def _actual(self,ctx):return {i:float(ctx.positions[i].quantity) for i in self.by_id}
    def _flat(self,ctx):return all(q==0 for q in self._actual(ctx).values())
    def _tol(self,i):return max(EPS,self.by_id[i].lot_size*1e-6)
    def _row(self,now):
        idx=self.features.index.searchsorted(now,side='right')-1
        if idx<0 or now-self.features.index[idx]>pd.Timedelta(minutes=2):return None
        return self.features.iloc[idx]
    def _daily(self,now):return now.hour==0 and now.minute==5 and now.second==0 and now.microsecond==0 and now.nanosecond==0
    def _weekly(self,now):return self._daily(now) and now.dayofweek==6

    def _yield(self,row,symbol):
        if row is None:return None
        flag=row[f'valid_{symbol}']
        if pd.isna(flag) or flag not in (True,False,0,1) or not bool(flag):return None
        try:value=float(row[f'yield_{symbol}'])
        except (ValueError,TypeError):return None
        return value if math.isfinite(value) else None

    def _select(self,ctx,row):
        values={s:self._yield(row,s) for s in SYMBOLS}
        prices={s:self._price(row,s) for s in SYMBOLS}
        if any(v is None for v in values.values()) or any(p is None for p in prices.values()):
            self._log(ctx,'PROPOSAL_REJECTED',reason='all_eight_valid_required');return None
        ranks=sorted(SYMBOLS,key=lambda s:(values[s],SYMBOLS.index(s)))
        longs=ranks[:2];shorts=ranks[-2:]
        gap=sum(values[s] for s in shorts)/2-sum(values[s] for s in longs)/2
        if gap<=0:
            self._log(ctx,'PROPOSAL_REJECTED',reason='nonpositive_rank_gap');return None
        proposal=dict(longs=longs,shorts=shorts,ranks=ranks,yields=values,gap=gap,
                      selected_at=ctx.now,expires=ctx.now+pd.Timedelta(minutes=15))
        self._log(ctx,'WEEKLY_PROPOSAL',**proposal)
        return proposal

    def _price(self,row,s):
        if row is None:return None
        try:p=float(row[f'price_{s}'])
        except (ValueError,TypeError):return None
        return p if math.isfinite(p) and p>0 else None

    def _risk(self,ctx):
        events=ctx.portfolio.events[self._event_cursor:];self._event_cursor=len(ctx.portfolio.events)
        if any(e['type']=='LIQUIDATION' for e in events):return 'actual_liquidation'
        p=ctx.portfolio;eq=p.venue_equity('binance')
        if not math.isfinite(eq) or eq<=.8*p.config.initial_balances['binance']:return 'equity_floor'
        if p.available('binance')<=0:return 'nonpositive_available'
        if p.margin_used('binance')>=.8*eq:return 'margin_utilization'
        gross=sum(p.exposure('binance'))
        if gross>.5*eq+EPS:return 'gross_limit'
        if any(abs(q)*p.marks.get(i,0)>.25*eq+EPS for i,q in self._actual(ctx).items()):return 'position_limit'
        reserve=p.maintenance_margin('binance')+sum(abs(q)*p.marks.get(i,0)*(self.by_id[i].taker_bps+self.by_id[i].liquidation_bps)/10000 for i,q in self._actual(ctx).items())
        if reserve>=.8*eq:return 'maintenance_close_reserve'
        if any(abs(q)>=EPS and (not math.isfinite(p.marks.get(i,0)) or p.marks.get(i,0)<=0) for i,q in self._actual(ctx).items()):return 'invalid_current_mark'
        return None

    def _plan(self,ctx,row):
        if not self._flat(ctx):return None,'not_actual_flat'
        p=ctx.portfolio;eq=p.equity();budget=eq*.25/4
        if not math.isfinite(budget) or budget<=0:return None,'invalid_equity'
        targets={i:0. for i in self.by_id};notionals={};fees=slip=margin=reserve=forecast=cost=0.
        for symbol in self.proposal['longs']+self.proposal['shorts']:
            spec=self.instruments[symbol];price=self._price(row,symbol)
            if price is None:return None,'missing_available_price'
            q=native_quantity(budget,price,spec.lot_size)
            if q<=0 or q<spec.min_quantity-EPS or q*price<spec.min_notional-EPS:return None,'opening_minimum:'+symbol
            side=1 if symbol in self.proposal['longs'] else -1
            mark=float(p.marks.get(spec.id,0))
            if not math.isfinite(mark) or mark<=0:return None,'missing_current_mark'
            execution=adverse_price(mark,side,spec,p.config,q,None)
            fee=q*execution*spec.taker_bps/10000
            ok,reason=p.admissible(spec.id,side,q,execution,fee)
            if not ok:return None,'core_'+reason
            targets[spec.id]=side*q;notionals[symbol]=q*price
            fees+=fee;slip+=max(0,side*(execution-mark)*q);margin+=q*mark
            reserve+=q*mark*(spec.maintenance_rate+(spec.taker_bps+spec.liquidation_bps)/10000)
            forecast-=side*q*price*self.proposal['yields'][symbol]*168
            cost+=2*q*price*(spec.taker_bps+p.config.slippage_bps)/10000
        future_eq=eq-fees-slip
        plan=dict(targets=targets,notionals=notionals,entry_equity=eq,per_leg_budget=budget,
                  indicative_funding_168h=forecast,indicative_roundtrip_cost=cost,proposal=dict(self.proposal))
        self._log(ctx,'ADMISSION_DIAGNOSTIC',**plan)
        if margin+fees+slip>=p.available('binance'):return None,'joint_available_margin'
        if future_eq<=0 or margin>.5*future_eq+EPS or margin>p.config.max_gross_leverage*future_eq+EPS:return None,'joint_gross_limit'
        if margin>=.8*future_eq or reserve>=.8*future_eq:return None,'joint_margin_reserve'
        if any(abs(q)*p.marks[i]>p.config.max_position_pct*future_eq+EPS for i,q in targets.items()):return None,'joint_position_limit'
        return plan,''

    def _submit(self,ctx,targets,kind,plan=None):
        actual=self._actual(ctx);orders={}
        self.transaction=dict(kind=kind,targets=dict(targets),start=actual,orders=orders,plan=plan,
                              submitted_at=ctx.now,deadline=ctx.now+pd.Timedelta(milliseconds=ctx.portfolio.config.latency_ms)+pd.Timedelta(minutes=ctx.portfolio.config.execution_delay_bars+5))
        self.last_targets=dict(targets);self.state=kind
        for iid in self.by_id:
            delta=targets[iid]-actual[iid]
            if delta==0 or (kind=='ENTERING' and abs(delta)<=self._tol(iid)):continue
            q=floor_step(abs(delta),self.by_id[iid].lot_size)
            if q<=0 or q<self.by_id[iid].min_quantity-EPS or abs(q-abs(delta))>self._tol(iid):
                self._abort(ctx,'unexecutable_transaction_dust');return
            order=Order(iid,1 if delta>0 else -1,q,tif='GTC',reduce_only=kind=='EXITING')
            ctx.order(order);orders[iid]=order
        self._log(ctx,'TARGET_SUBMITTED',transition=kind,targets=targets,deadline=self.transaction['deadline'],order_ids=[o.id for o in orders.values()])
        if any(o.status=='rejected' for o in orders.values()):self._abort(ctx,'submission_rejected')

    def _cancel(self,ctx,orders):
        for o in orders.values():
            if o.status in LIVE:ctx.cancel(o.id)

    def _abort(self,ctx,reason):
        if self.abort_latched and self.state in ('ABORTING','BLOCKED'):
            self._cleanup(ctx);return
        self.abort_latched=True
        self.cleanup_deadline=ctx.now+pd.Timedelta(milliseconds=ctx.portfolio.config.latency_ms)+pd.Timedelta(minutes=ctx.portfolio.config.execution_delay_bars+5)
        self.cleanup_deadline_exceeded=False
        if self.transaction:self._cancel(ctx,self.transaction['orders'])
        self.transaction=None;self.proposal=None;self.state='ABORTING';self._log(ctx,'ACCOUNT_ABORT',reason=reason,cleanup_deadline=self.cleanup_deadline)
        self._cleanup(ctx)

    def _cleanup(self,ctx):
        self.last_targets={i:0. for i in self.by_id}
        for iid,q in self._actual(ctx).items():
            old=self.cleanup_orders.get(iid)
            if q==0:
                if old and old.status in LIVE:ctx.cancel(old.id)
                self.cleanup_orders.pop(iid,None);continue
            spec=self.by_id[iid];size=floor_step(abs(q),spec.lot_size)
            if size<=0 or size<spec.min_quantity-EPS or abs(size-abs(q))>self._tol(iid):
                if old and old.status in LIVE:ctx.cancel(old.id)
                if iid not in self.blocked:self._log(ctx,'BLOCKED_DUST',instrument_id=iid,quantity=q)
                self.blocked.add(iid);self.state='BLOCKED';continue
            if old and old.status in LIVE:continue
            if old:
                if iid not in self.blocked:self._log(ctx,'BLOCKED_CLEANUP',instrument_id=iid,quantity=q,order_status=old.status,order_id=old.id)
                self.blocked.add(iid);self.state='BLOCKED';continue
            order=Order(iid,-1 if q>0 else 1,size,tif='GTC',reduce_only=True)
            ctx.order(order);self.cleanup_orders[iid]=order
        if self.cleanup_deadline is not None and ctx.now>=self.cleanup_deadline and not self._flat(ctx) and not self.cleanup_deadline_exceeded:
            self.cleanup_deadline_exceeded=True;self.state='BLOCKED'
            self._log(ctx,'CLEANUP_DEADLINE_EXCEEDED',deadline=self.cleanup_deadline)
        if self._flat(ctx) and not any(o.status in LIVE for o in self.cleanup_orders.values()):
            self.active=None;self.state='COOLDOWN';self.cleanup_orders={};self.blocked.clear();self.cooldown_until=ctx.now+COLD
            self._log(ctx,'ABORT_FLAT',cooldown_until=self.cooldown_until)

    def _progress(self,ctx):
        tx=self.transaction;actual=self._actual(ctx)
        for i,target in tx['targets'].items():
            q=actual[i];start=tx['start'][i];tol=self._tol(i)
            if q<min(start,target)-tol or q>max(start,target)+tol:self._abort(ctx,'quantity_overshoot');return
            reached=abs(q-target)<=tol;o=tx['orders'].get(i)
            if o and reached and o.status in LIVE:ctx.cancel(o.id)
            if o and not reached and o.status in ('rejected','cancelled','filled'):self._abort(ctx,'unmet_terminal_order');return
        if all(abs(actual[i]-q)<=self._tol(i) for i,q in tx['targets'].items()):
            self._cancel(ctx,tx['orders'])
            if tx['kind']=='ENTERING':
                ids={o.id for o in tx['orders'].values()}
                fill_times=[pd.Timestamp(f['timestamp']) for f in ctx.portfolio.fills if f.get('order_id') in ids]
                completed_at=max(fill_times) if fill_times else ctx.now
                if completed_at>tx['deadline']:self._abort(ctx,'entry_completion_after_deadline');return
                self.active=dict(tx['plan'],completed_at=completed_at,observed_completed_at=ctx.now,generation=self.generation)
                self.completed_baskets.append(dict(timestamp=completed_at,completed_at=completed_at,observed_completed_at=ctx.now,generation=self.generation,
                    symbols=tx['plan']['proposal']['longs']+tx['plan']['proposal']['shorts'],
                    targets=dict(tx['targets']),proposal=dict(tx['plan']['proposal'])))
                self.state='HOLDING';self.proposal=None
            else:
                # Closing tolerances do not permit a nonzero dust position to be
                # declared flat. All old orders must be resolved before re-entry.
                if not self._flat(ctx):self._abort(ctx,'closing_residual_dust');return
                self.active=None;self.state='IDLE'
            self._log(ctx,'TARGET_COMPLETE',transition=tx['kind'],targets=tx['targets'])
            self.transaction=None
        elif ctx.now>=tx['deadline']:self._abort(ctx,'five_minute_timeout')

    def _close(self,ctx,reason):
        self._log(ctx,'BASKET_EXIT',reason=reason)
        self._submit(ctx,{i:0. for i in self.by_id},'EXITING')

    def _enter(self,ctx,row):
        if ctx.now>=self.proposal['expires'] or ctx.now>=self.stop-HOLD:
            self._log(ctx,'PROPOSAL_EXPIRED',reason='expiry_or_final_seven_days');self.proposal=None;self.state='IDLE';return
        plan,reason=self._plan(ctx,row)
        if plan is None:
            self._log(ctx,'ADMISSION_REJECTED',reason=reason);self.proposal=None;self.state='IDLE';return
        self.generation+=1;self._submit(ctx,plan['targets'],'ENTERING',plan)

    def _record_unmatched(self,ctx):
        if self.state not in ('ENTERING','EXITING','ABORTING','BLOCKED'):return
        actual=self._actual(ctx)
        if not any(q!=0 for q in actual.values()):return
        notionals={i:q*ctx.portfolio.marks.get(i,0) for i,q in actual.items()}
        self.unmatched.append(dict(timestamp=ctx.now,generation=self.generation,state=self.state,
            quantities=actual,marked_notionals=notionals,gross=sum(abs(n) for n in notionals.values()),
            net=sum(notionals.values()),targets=dict(self.last_targets)))

    def on_bars(self,ctx,bars):
        self._catalog(ctx)
        if {b['instrument_id'] for b in bars}!=set(self.by_id):raise ValueError('Complete simultaneous eight-instrument slice required')
        self._record_unmatched(ctx)
        reason=self._risk(ctx)
        if ctx.now>=self.stop:return
        if ctx.now>=self.stop-pd.Timedelta(minutes=10) and not self.terminal_requested:
            self.terminal_requested=True;self.proposal=None
            self._log(ctx,'TERMINAL_EXIT_REQUEST')
            if self.transaction and self.transaction['kind']=='ENTERING':
                self._cancel(ctx,self.transaction['orders']);self.transaction=None
            # A valid existing exit/cleanup remains immutable, including deadline.
            if self.transaction is None and self.state not in ('ABORTING','BLOCKED') and reason is None:
                if not self._flat(ctx):self._close(ctx,'terminal_ten_minutes');return
                self.active=None;self.state='IDLE';self._log(ctx,'TERMINAL_FLAT')
        if self.state in ('ABORTING','BLOCKED'):
            if reason=='actual_liquidation':self._log(ctx,'LIQUIDATION_DURING_CLEANUP')
            self._cleanup(ctx);return
        if reason:
            if self.transaction or self.active or not self._flat(ctx) or reason=='actual_liquidation':self._abort(ctx,reason)
            elif reason!=self._risk_latch:self._log(ctx,'ACCOUNT_RISK_BLOCKED',reason=reason)
            self._risk_latch=reason;return
        self._risk_latch=None
        row=self._row(ctx.now)
        if self.transaction:self._progress(ctx);return
        if self.active:
            if self._weekly(ctx.now):
                self.proposal=self._select(ctx,row) if ctx.now<self.stop-HOLD else None
                self._close(ctx,'scheduled_weekly_roll');return
            if ctx.now-self.active['completed_at']>=HOLD:
                self.proposal=None;self._close(ctx,'seven_day_safety');return
            if self._daily(ctx.now):
                basket=self.active['proposal'];rates={s:self._yield(row,s) for s in basket['longs']+basket['shorts']}
                gap=None if any(v is None for v in rates.values()) else sum(rates[s] for s in basket['shorts'])/2-sum(rates[s] for s in basket['longs'])/2
                if gap is None or gap<=0:self.proposal=None;self._close(ctx,'daily_invalid_or_nonpositive_gap');return
            return
        if self.terminal_requested:return
        if self.state=='COOLDOWN':
            if ctx.now<self.cooldown_until:return
            self.state='IDLE'
        if self.proposal:self._enter(ctx,row);return
        if self.cooldown_until is not None and ctx.now<self.cooldown_until:return
        if self._weekly(ctx.now) and ctx.now<self.stop-HOLD:
            self.proposal=self._select(ctx,row)
            if self.proposal:self._enter(ctx,row)


FundingRank=FundingRankPortfolio
