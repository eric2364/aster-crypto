"""Prospective native-OI stabilization/rebound policy; no loading or estimation.

Reuses frozen candidate27 account and immutable-order controls, not its funding
selection or lifecycle. The transitive source must be archived by the new runner.
"""
import math
import pandas as pd
from examples.funding_rank.strategy import FundingRankPortfolio,SYMBOLS,LIVE,EPS,native_quantity
from aster.backtest.execution import adverse_price

HOLD=pd.Timedelta(hours=4)
NORMAL_COLD=pd.Timedelta(hours=1)
FIELDS={'price','price_return_1h','price_return_15m','quantity_change_1h','quantity_change_5m','valid','instrument_id','metric_available_at','price_available_at'}


class PositioningPortfolio(FundingRankPortfolio):
    version='prospective-native-oi-stabilization-rebound-1'
    def __init__(self,features,stop):
        ids={f'binance:perpetual:{"1000PEPEUSDT" if s=="PEPEUSDT" else s}' for s in SYMBOLS}
        if not isinstance(features,dict) or set(features)!=ids:raise ValueError('Exact eight native feature streams required')
        self.features={};common=None
        for iid,frame in features.items():
            clock=pd.DatetimeIndex(frame.index)
            if clock.tz is None or clock.hasnans or clock.has_duplicates or not clock.is_monotonic_increasing:
                raise ValueError('Sorted unique aware feature decision index required')
            clock=clock.tz_convert('UTC').as_unit('ns')
            if common is not None and not clock.equals(common):raise ValueError('Synchronized feature decision indexes required')
            common=clock
            if not FIELDS<=set(frame) or not frame.instrument_id.eq(iid).all():raise ValueError('Native feature identity/schema differs')
            if not pd.api.types.is_bool_dtype(frame.valid.dtype) or frame.valid.isna().any():raise ValueError('Nonmissing Boolean validity required')
            copy=frame.copy();copy.index=clock;self.features[iid]=copy
        self.stop=pd.Timestamp(stop)
        if self.stop.tzinfo is None:raise ValueError('Aware phase stop required')
        self.stop=self.stop.tz_convert('UTC')
        self.state='IDLE';self.active=None;self.proposal=None;self.transaction=None
        self.cleanup_orders={};self.cooldown_until=None;self.generation=0
        self.diagnostics=[];self.proposals=[];self.rejections=[];self.completed_entries=[];self.completed_episodes=[]
        self.completed_baskets=self.completed_episodes;self.matched_entries=self.completed_entries
        self.unmatched=[];self.last_targets={};self.blocked=set();self.episode=None
        self.instruments=None;self._event_cursor=0;self._risk_latch=None;self.terminal_requested=False
        self.cleanup_deadline=None;self.cleanup_deadline_exceeded=False;self.abort_latched=False
        self._known_order_ids=set();self._live_event_ids=set();self._order_event_cursor=0

    def _log(self,ctx,kind,**values):
        if kind=='TARGET_SUBMITTED':self._known_order_ids.update(values['order_ids'])
        if kind=='ABORT_FLAT':
            self.cooldown_until=ctx.now+NORMAL_COLD;values['cooldown_until']=self.cooldown_until
        event=dict(timestamp=ctx.now,type=kind,generation=self.generation);event.update(values);self.diagnostics.append(event)
        if kind=='EVENT_PROPOSAL':self.proposals.append(dict(event))
        if 'REJECTED' in kind or kind=='ACCOUNT_RISK_BLOCKED':self.rejections.append(dict(event))

    def _flat(self,ctx):
        return super()._flat(ctx) and not self._live_event_ids

    def _feature(self,now,iid):
        frame=self.features[iid];idx=frame.index.searchsorted(now,side='right')-1
        if idx<0 or now-frame.index[idx]>pd.Timedelta(minutes=2):return None
        row=frame.iloc[idx]
        if not bool(row.valid):return None
        for field in ('price','price_return_1h','price_return_15m','quantity_change_1h','quantity_change_5m'):
            try:value=float(row[field])
            except (TypeError,ValueError):return None
            if not math.isfinite(value) or (field=='price' and value<=0):return None
        # Builder defines causal availability; source fields also fail closed if
        # provided. Publication assumptions are not manufactured in the policy.
        for field,strict in [('metric_available_at',True),('price_available_at',False)]:
            if field in row:
                if pd.isna(row[field]):return None
                t=pd.Timestamp(row[field])
                if t.tzinfo is None or (t>=now if strict else t>now):return None
                if field=='metric_available_at' and now-t>pd.Timedelta(minutes=5):return None
                if field=='price_available_at' and now-t>pd.Timedelta(minutes=2):return None
        if 'metric_age_seconds' in row and (not math.isfinite(float(row.metric_age_seconds)) or not 0<=float(row.metric_age_seconds)<=300):return None
        return row

    def _eligible(self,row):
        return row is not None and float(row.quantity_change_1h)<=-.02 and float(row.quantity_change_5m)>=0 and float(row.price_return_1h)<=-.015 and float(row.price_return_15m)>=.003

    def _review(self,now):return now.minute%5==0 and now.second==0 and now.microsecond==0 and now.nanosecond==0

    def _plan(self,ctx,symbol,row):
        if not self._flat(ctx):return None,'not_actual_flat'
        p=ctx.portfolio;spec=self.instruments[symbol];price=float(row.price);eq=p.venue_equity('binance');budget=.1*eq
        if not math.isfinite(budget) or budget<=0:return None,'invalid_equity'
        q=native_quantity(budget,price,spec.lot_size)
        if q<=0 or q<spec.min_quantity-EPS or q*price<spec.min_notional-EPS:return None,'opening_minimum'
        mark=float(p.marks.get(spec.id,0))
        if not math.isfinite(mark) or mark<=0:return None,'invalid_current_mark'
        execution=adverse_price(mark,1,spec,p.config,q,None);fee=q*execution*spec.taker_bps/10000
        ok,reason=p.admissible(spec.id,1,q,execution,fee)
        if not ok:return None,'core_'+reason
        margin=q*mark;slip=max(0,q*(execution-mark));future_eq=eq-fee-slip
        reserve=margin*(spec.maintenance_rate+(spec.taker_bps+spec.liquidation_bps)/10000)
        if margin+fee+slip>=p.available('binance'):return None,'available_margin'
        if future_eq<=0 or margin>min(.5,p.config.max_gross_leverage)*future_eq+EPS:return None,'gross_limit'
        if margin>min(.25,p.config.max_position_pct)*future_eq+EPS:return None,'position_limit'
        if margin>=.8*future_eq or reserve>=.8*future_eq:return None,'margin_reserve'
        targets={i:0. for i in self.by_id};targets[spec.id]=q
        return dict(symbol=symbol,instrument_id=spec.id,targets=targets,budget=budget,entry_equity=eq,
            price=price,quantity=q,selected_at=ctx.now,features={f:float(row[f]) for f in ('price','price_return_1h','price_return_15m','quantity_change_1h','quantity_change_5m')}),''

    def _finish_episode(self,ctx,failed):
        if self.episode is None:return
        closes=[pd.Timestamp(f['timestamp']) for f in ctx.portfolio.fills if f.get('instrument_id')==self.episode['instrument_id'] and f.get('side',0)<0 and pd.Timestamp(f['timestamp'])>=self.episode['submitted_at']]
        row=dict(self.episode,closed_at=max(closes) if closes else ctx.now,observed_closed_at=ctx.now,failed=failed or self.episode['entry_completed_at'] is None)
        if row.get('entry_completed_at') is not None and not row['failed']:self.completed_episodes.append(row)
        self._log(ctx,'EPISODE_CLOSED',**row)
        self.episode=None

    def _cleanup(self,ctx):
        had=self.episode is not None
        super()._cleanup(ctx)
        self._known_order_ids.update(o.id for o in self.cleanup_orders.values())
        if had and self.state=='COOLDOWN':self._finish_episode(ctx,True)

    def _close(self,ctx,reason):
        if self.episode is not None:self.episode['exit_reason']=reason
        self._log(ctx,'EPISODE_EXIT',reason=reason)
        self._submit(ctx,{i:0. for i in self.by_id},'EXITING')

    def _progress(self,ctx):
        tx=self.transaction;actual=self._actual(ctx)
        for i,target in tx['targets'].items():
            q=actual[i];start=tx['start'][i];tol=self._tol(i)
            if q<min(start,target)-tol or q>max(start,target)+tol:self._abort(ctx,'quantity_overshoot');return
            reached=abs(q-target)<=tol;o=tx['orders'].get(i)
            if o and reached and o.status in LIVE and tx['kind']=='EXITING':ctx.cancel(o.id)
            if o and not reached and o.status in ('rejected','cancelled','filled'):self._abort(ctx,'unmet_terminal_order');return
        reached=all(abs(actual[i]-q)<=self._tol(i) for i,q in tx['targets'].items())
        if tx['kind']=='ENTERING':reached=reached and all(o.status=='filled' for o in tx['orders'].values())
        if reached:
            self._cancel(ctx,tx['orders'])
            if tx['kind']=='ENTERING':
                ids={o.id for o in tx['orders'].values()};fills=[f for f in ctx.portfolio.fills if f.get('order_id') in ids]
                if not fills:self._abort(ctx,'target_without_actual_entry_fills');return
                completed_at=max(pd.Timestamp(f['timestamp']) for f in fills)
                if completed_at>tx['deadline']:self._abort(ctx,'entry_completion_after_deadline');return
                plan=dict(tx['plan']);plan.update(completed_at=completed_at,observed_completed_at=ctx.now,
                    average_entry_price=float(ctx.positions[plan['instrument_id']].average_price),generation=self.generation)
                self.active=plan;self.state='HOLDING';self.episode['entry_completed_at']=completed_at
                self.episode['average_entry_price']=plan['average_entry_price'];self.completed_entries.append(dict(plan))
                self._log(ctx,'ENTRY_COMPLETE',**plan)
            else:
                if not self._flat(ctx):self._abort(ctx,'closing_residual_dust');return
                self.active=None;self._finish_episode(ctx,False);self.state='COOLDOWN';self.cooldown_until=ctx.now+NORMAL_COLD
                self._log(ctx,'NORMAL_FLAT',cooldown_until=self.cooldown_until)
            self.transaction=None
        elif ctx.now>=tx['deadline']:self._abort(ctx,'five_minute_timeout')

    def _exit_reason(self,ctx):
        plan=self.active or (self.transaction['plan'] if self.transaction and self.transaction['kind']=='ENTERING' else None)
        if plan is None:return None
        iid=plan['instrument_id'];row=self._feature(ctx.now,iid)
        if row is None:return 'invalid_or_stale_feature'
        q=float(ctx.positions[iid].quantity);avg=float(ctx.positions[iid].average_price)
        if q>0 and avg>0 and float(row.price)<=avg*.98:return 'closed_price_adverse_two_percent'
        if self.active and ctx.now>=self.active['completed_at']+HOLD:return 'four_hour_hold'
        return None

    def on_bars(self,ctx,bars):
        self._catalog(ctx)
        if {b['instrument_id'] for b in bars}!=set(self.by_id):raise ValueError('Complete eight-native slice required')
        self._record_unmatched(ctx);reason=self._risk(ctx)
        unknown_accepted=set()
        for event in ctx.portfolio.events[self._order_event_cursor:]:
            if event['type']=='ORDER_ACCEPTED':
                self._live_event_ids.add(event['order_id'])
                if event['order_id'] not in self._known_order_ids:unknown_accepted.add(event['order_id'])
            elif event['type'] in ('ORDER_CANCELLED','ORDER_REJECTED','ORDER_FILLED'):self._live_event_ids.discard(event['order_id'])
        self._order_event_cursor=len(ctx.portfolio.events)
        unknown=self._live_event_ids-self._known_order_ids
        if unknown or unknown_accepted:
            for oid in sorted(unknown):ctx.cancel(oid)
            reason='unowned_live_order' if unknown else 'unowned_order_event'
        selected=(self.active or (self.transaction['plan'] if self.transaction and self.transaction['kind']=='ENTERING' else {}) or {}).get('instrument_id')
        if self.state not in ('EXITING','ABORTING','BLOCKED') and any(q!=0 and (i!=selected or q<0) for i,q in self._actual(ctx).items()):reason='unexpected_native_inventory'
        if self.state=='HOLDING' and self.active and reason is None:
            actual=self._actual(ctx)
            if any(abs(actual[i]-target)>self._tol(i) for i,target in self.active['targets'].items()):
                reason='unexpected_holding_quantity'
        if ctx.now>=self.stop:return
        if ctx.now>=self.stop-pd.Timedelta(minutes=10) and not self.terminal_requested:
            self.terminal_requested=True;self.proposal=None;self._log(ctx,'TERMINAL_EXIT_REQUEST')
            if self.transaction and self.transaction['kind']=='ENTERING':
                self._cancel(ctx,self.transaction['orders']);self.transaction=None
                if self.episode is not None:self.episode['exit_reason']='terminal_partial_entry'
            if self.transaction is None and self.state not in ('ABORTING','BLOCKED') and reason is None:
                if not self._flat(ctx):self._close(ctx,'terminal_ten_minutes');return
                self.active=None;self.state='IDLE';self._finish_episode(ctx,True);self._log(ctx,'TERMINAL_FLAT')
        if self.state in ('ABORTING','BLOCKED'):
            if reason=='actual_liquidation':self._log(ctx,'LIQUIDATION_DURING_CLEANUP')
            self._cleanup(ctx);return
        if reason:
            if self.transaction or self.active or not self._flat(ctx) or reason in ('actual_liquidation','unowned_live_order','unowned_order_event'):self._abort(ctx,reason)
            else:self._log(ctx,'ACCOUNT_RISK_BLOCKED',reason=reason)
            return
        exit_reason=self._exit_reason(ctx)
        if exit_reason and (self.state=='HOLDING' or self.transaction and self.transaction['kind']=='ENTERING'):
            if self.transaction:self._abort(ctx,'partial_entry_'+exit_reason)
            else:self._close(ctx,exit_reason)
            return
        if self.transaction:self._progress(ctx);return
        if self.active:return
        if self.state=='COOLDOWN':
            if ctx.now<self.cooldown_until:return
            self.state='IDLE';self.abort_latched=False;self.cleanup_orders={};self.cleanup_deadline=None;self.cleanup_deadline_exceeded=False
        if self.terminal_requested or ctx.now>=self.stop-HOLD-pd.Timedelta(minutes=10) or not self._review(ctx.now):return
        if not self._flat(ctx):self._abort(ctx,'unexpected_not_flat');return
        eligible=[(s,self._feature(ctx.now,self.instruments[s].id)) for s in SYMBOLS]
        eligible=[(s,row) for s,row in eligible if self._eligible(row)]
        if not eligible:return
        symbol,row=eligible[0];self._log(ctx,'EVENT_PROPOSAL',symbol=symbol,eligible_symbols=[s for s,_ in eligible])
        plan,why=self._plan(ctx,symbol,row)
        if plan is None:
            self.cooldown_until=ctx.now+NORMAL_COLD;self.state='COOLDOWN'
            self._log(ctx,'ADMISSION_REJECTED',symbol=symbol,reason=why,cooldown_until=self.cooldown_until);return
        self.generation+=1;self.episode=dict(generation=self.generation,symbol=symbol,instrument_id=plan['instrument_id'],submitted_at=ctx.now,entry_completed_at=None,exit_reason=None)
        self._submit(ctx,plan['targets'],'ENTERING',plan)
