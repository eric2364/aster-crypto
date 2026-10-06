"""Prospective native paired-venue carry coordinator; no data loading or fitting."""
import math
import pandas as pd
from aster.backtest.models import Order
from aster.backtest.execution import floor_step, adverse_price
from aster.strategies.base import BaseStrategy
from examples.cross_venue.units import common_native_step, bounded_pair_quantity

SYMBOLS=('BTCUSDT','ETHUSDT','DOGEUSDT','PEPEUSDT','SOLUSDT','XRPUSDT','LINKUSDT','ADAUSDT')
VENUES=('binance','bybit')
LEG_CAP=1250.
HORIZON=pd.Timedelta(hours=168)
COOLDOWN=pd.Timedelta(hours=24)
EPS=1e-9


class CrossVenueCarry(BaseStrategy):
    version='prospective-cross-venue-funding-differential-1'
    def __init__(self,features,stop):
        clock=pd.DatetimeIndex(features.index)
        if clock.tz is None or clock.hasnans or clock.has_duplicates or not clock.is_monotonic_increasing:
            raise ValueError('Unique sorted timezone-aware availability index required')
        required={f'{field}_{venue}_{symbol}' for symbol in SYMBOLS for venue in VENUES
                  for field in ('yield','valid','price')}
        if not required<=set(features.columns): raise ValueError('Missing paired available feature columns')
        self.features=features.copy(); self.features.index=clock.tz_convert('UTC').as_unit('ns')
        self.stop=pd.Timestamp(stop)
        if self.stop.tzinfo is None: raise ValueError('UTC-aware stop required')
        self.stop=self.stop.tz_convert('UTC')
        self.instruments=None; self.pairs={s:{'state':'IDLE','orders':{},'cleanup':{},'cooldown':None} for s in SYMBOLS}
        self.diagnostics=[]; self.unmatched=[]; self.last_targets={}; self.matched_entries=[]
        self.global_abort=False; self.global_cooldown=None; self._event_cursor=0; self._risk_latch=None
        self._blocked=set()

    def _catalog(self,ctx):
        if self.instruments is not None:return
        native={(s.exchange,s.symbol):s for s in ctx.instruments.values()}
        if len(native)!=16 or len(ctx.instruments)!=16: raise ValueError('Exactly sixteen declared venue instruments required')
        self.instruments={symbol:{venue:native[(venue,'1000PEPEUSDT' if symbol=='PEPEUSDT' else symbol)]
                                  for venue in VENUES} for symbol in SYMBOLS}
        for pair in self.instruments.values(): common_native_step(pair['binance'],pair['bybit'])
        if set(ctx.portfolio.cash)!=set(VENUES):raise ValueError('Two independently funded venue wallets required')
        if ctx.portfolio.config.margin_mode!='cross' or ctx.portfolio.config.leverage!=1:
            raise ValueError('Protocol requires cash-only cross margin and leverage one')
        self.last_targets={s.id:0. for s in ctx.instruments.values()}

    def _log(self,ctx,kind,**details): self.diagnostics.append({'timestamp':ctx.now,'type':kind,**details})
    def _quantity(self,ctx,iid):return float(ctx.positions[iid].quantity)
    def _tolerance(self,spec):return max(EPS,spec.lot_size*1e-6)
    def _flat(self,ctx,symbol):return all(abs(self._quantity(ctx,s.id))<EPS for s in self.instruments[symbol].values())
    def _row(self,now):
        # Availability only: never read or interpolate a future row.
        index=self.features.index.searchsorted(now,side='right')-1
        if index<0 or now-self.features.index[index]>pd.Timedelta(minutes=2):return None
        return self.features.iloc[index]
    def _decision(self,now):return now.minute==5 and now.second==0 and now.microsecond==0 and now.nanosecond==0

    def _values(self,row,symbol):
        if row is None:return None
        values={}
        for venue in VENUES:
            flag=row[f'valid_{venue}_{symbol}']
            if pd.isna(flag) or flag not in (True,False,0,1) or not bool(flag):return None
            try:
                rate=float(row[f'yield_{venue}_{symbol}']); price=float(row[f'price_{venue}_{symbol}'])
            except (TypeError,ValueError):return None
            if not math.isfinite(rate) or not math.isfinite(price) or price<=0:return None
            values[venue]=(rate,price)
        return values

    def _admission(self,ctx,symbol,row):
        values=self._values(row,symbol)
        if values is None:return None,'invalid_feature'
        b,y=self.instruments[symbol]['binance'],self.instruments[symbol]['bybit']
        rb,pb=values['binance']; ry,py=values['bybit']; gap=ry-rb
        if gap==0:return None,'zero_gap'
        quantity=bounded_pair_quantity(min(LEG_CAP/pb,LEG_CAP/py),b,y)
        if quantity<=0:return None,'common_quantity_minimum'
        if quantity*pb<b.min_notional-EPS or quantity*py<y.min_notional-EPS:return None,'opening_notional_minimum'
        cost=2*quantity*(pb*.0026+py*.0028)
        reference=quantity*(pb+py)/2
        forecast=reference*abs(gap)*168
        if forecast<1.5*cost:return None,'stress_cost_filter'
        direction=1 if gap>0 else -1
        targets={b.id:direction*quantity,y.id:-direction*quantity}
        # Independent wallets: no sibling closing credits or opposite-venue cash.
        for venue,spec in [('binance',b),('bybit',y)]:
            mark=float(ctx.portfolio.marks.get(spec.id,0))
            if not math.isfinite(mark) or mark<=0:return None,'missing_execution_mark'
            side=1 if targets[spec.id]>0 else -1
            price=adverse_price(mark,side,spec,ctx.portfolio.config,quantity,None)
            fee=quantity*price*spec.taker_bps/10000
            ok,reason=ctx.portfolio.admissible(spec.id,side,quantity,price,fee)
            if not ok:return None,'venue_'+venue+'_'+reason
        return {'symbol':symbol,'quantity':quantity,'direction':direction,'entry_cost':cost,
                'forecast':forecast,'targets':targets,'submitted_at':ctx.now},''

    def _start(self,ctx,symbol,basket):
        pair=self.pairs[symbol]; pair.update(state='OPENING',basket=basket,orders={},start={})
        delay=pd.Timedelta(milliseconds=ctx.portfolio.config.latency_ms)+pd.Timedelta(minutes=ctx.portfolio.config.execution_delay_bars)
        pair['deadline']=ctx.now+delay+pd.Timedelta(minutes=5)
        for iid,target in basket['targets'].items():
            pair['start'][iid]=self._quantity(ctx,iid)
            order=Order(iid,1 if target>0 else -1,abs(target),tif='GTC')
            ctx.order(order);pair['orders'][iid]=order;self.last_targets[iid]=target
        self._log(ctx,'PAIR_SUBMITTED',symbol=symbol,targets=basket['targets'],deadline=pair['deadline'],
                  entry_cost=basket['entry_cost'],forecast=basket['forecast'])
        if any(o.status=='rejected' for o in pair['orders'].values()):self._abort_pair(ctx,symbol,'submission_rejected')

    def _abort_pair(self,ctx,symbol,reason):
        pair=self.pairs[symbol]
        for order in pair['orders'].values():
            if order.status in ('accepted','partial'):ctx.cancel(order.id)
        pair['orders']={};pair['state']='ABORT'
        self._log(ctx,'PAIR_ABORT',symbol=symbol,reason=reason)
        self._cleanup(ctx,symbol)

    def _begin_close(self,ctx,symbol,reason):
        pair=self.pairs[symbol];pair['state']='CLOSING'
        self._log(ctx,'PAIR_EXIT',symbol=symbol,reason=reason)
        self._cleanup(ctx,symbol)

    def _cleanup(self,ctx,symbol):
        pair=self.pairs[symbol]
        for spec in self.instruments[symbol].values():
            iid=spec.id;quantity=self._quantity(ctx,iid);order=pair['cleanup'].get(iid)
            self.last_targets[iid]=0.
            if abs(quantity)<EPS:
                if order and order.status in ('accepted','partial'):ctx.cancel(order.id)
                pair['cleanup'].pop(iid,None);continue
            rounded=floor_step(abs(quantity),spec.lot_size)
            if rounded<spec.min_quantity-EPS or abs(rounded-abs(quantity))>self._tolerance(spec):
                if order and order.status in ('accepted','partial'):ctx.cancel(order.id)
                if iid not in self._blocked:self._log(ctx,'BLOCKED_DUST',symbol=symbol,instrument_id=iid,quantity=quantity)
                self._blocked.add(iid);continue
            if order and order.status in ('accepted','partial'):continue
            order=Order(iid,-1 if quantity>0 else 1,rounded,tif='GTC',reduce_only=True)
            ctx.order(order);pair['cleanup'][iid]=order
        if self._flat(ctx,symbol) and not any(o.status in ('accepted','partial') for o in pair['cleanup'].values()):
            pair.update(state='IDLE',cleanup={},orders={},cooldown=ctx.now+COOLDOWN)
            pair.pop('basket',None)
            self._log(ctx,'PAIR_FLAT',symbol=symbol,cooldown=pair['cooldown'])

    def _progress(self,ctx,symbol):
        pair=self.pairs[symbol];targets=pair['basket']['targets'];reached=True
        for spec in self.instruments[symbol].values():
            iid=spec.id;actual=self._quantity(ctx,iid);target=targets[iid];start=pair['start'][iid]
            tolerance=self._tolerance(spec)
            if actual<min(start,target)-tolerance or actual>max(start,target)+tolerance:
                self._abort_pair(ctx,symbol,'quantity_overshoot');return
            complete=abs(actual-target)<=tolerance;reached &=complete
            order=pair['orders'][iid]
            if complete and order.status in ('accepted','partial'):ctx.cancel(order.id)
            if not complete and order.status in ('rejected','cancelled','filled'):
                self._abort_pair(ctx,symbol,'unmet_terminal_order');return
        if reached:
            pair['state']='HOLDING';pair['orders']={}
            self.matched_entries.append({'timestamp':ctx.now,'symbol':symbol,'targets':dict(targets)})
            self._log(ctx,'PAIR_COMPLETE',symbol=symbol,targets=targets)
        elif ctx.now>=pair['deadline']:self._abort_pair(ctx,symbol,'five_minute_timeout')

    def _risk_reason(self,ctx):
        for venue in VENUES:
            equity=ctx.portfolio.venue_equity(venue)
            if equity<=.8*ctx.portfolio.config.initial_balances[venue]:return 'venue_equity_'+venue
            if ctx.portfolio.available(venue)<=0:return 'available_margin_'+venue
            long,short=ctx.portfolio.exposure(venue)
            if long+short>.5*equity+EPS:return 'venue_gross_'+venue
        return None

    def _abort_account(self,ctx,reason):
        if not self.global_abort:self._log(ctx,'ACCOUNT_ABORT',reason=reason)
        self.global_abort=True
        for symbol,pair in self.pairs.items():
            if pair['state']=='IDLE' and self._flat(ctx,symbol) and not pair['orders']:
                continue
            for order in pair['orders'].values():
                if order.status in ('accepted','partial'):ctx.cancel(order.id)
            pair['orders']={};pair['state']='ABORT'
            self._cleanup(ctx,symbol)
        if all(self._flat(ctx,s) for s in SYMBOLS):
            self.global_abort=False;self.global_cooldown=ctx.now+COOLDOWN
            self._log(ctx,'ACCOUNT_FLAT',cooldown=self.global_cooldown)

    def _risk(self,ctx):
        events=ctx.portfolio.events[self._event_cursor:];self._event_cursor=len(ctx.portfolio.events)
        liquidation=any(e['type']=='LIQUIDATION' for e in events)
        if liquidation:
            # Core may already have forcibly flattened every leg: still reset all
            # intent/basket state and start the account-wide post-cleanup cooldown.
            self._abort_account(ctx,'actual_liquidation')
            self._risk_latch='actual_liquidation';return True
        reason=self._risk_reason(ctx)
        if self.global_abort:
            self._abort_account(ctx,reason or 'continuing_cleanup');return True
        if reason:
            if any(not self._flat(ctx,s) or self.pairs[s]['orders'] for s in SYMBOLS):
                self._abort_account(ctx,reason)
            elif reason!=self._risk_latch:self._log(ctx,'ACCOUNT_RISK_BLOCKED',reason=reason)
            self._risk_latch=reason;return True
        self._risk_latch=None
        return self.global_cooldown is not None and ctx.now<self.global_cooldown

    def _record_unmatched(self,ctx):
        for symbol,specs in self.instruments.items():
            quantities={v:self._quantity(ctx,s.id) for v,s in specs.items()}
            delta=sum(quantities.values())
            if abs(delta)>max(self._tolerance(s) for s in specs.values()):
                marks={v:ctx.portfolio.marks.get(s.id,ctx.positions[s.id].average_price) for v,s in specs.items()}
                self.unmatched.append({'timestamp':ctx.now,'symbol':symbol,'native_delta':delta,
                    'approximate_unmatched_dollars':abs(delta)*sum(marks.values())/2,
                    'net_marked_notional':sum(quantities[v]*marks[v] for v in VENUES),
                    'quantities':quantities,'state':self.pairs[symbol]['state'],
                    'observation_semantics':'strategy callback before current open fills'})

    def on_funding(self,ctx,event):
        self._catalog(ctx);self._record_unmatched(ctx);self._risk(ctx)

    def on_bars(self,ctx,bars):
        self._catalog(ctx)
        if {b['instrument_id'] for b in bars}!=set(ctx.instruments):raise ValueError('Complete simultaneous sixteen-instrument slice required')
        self._record_unmatched(ctx)
        if self._risk(ctx):return
        row=self._row(ctx.now);decision=self._decision(ctx.now)
        for symbol,pair in self.pairs.items():
            if pair['state']=='OPENING':self._progress(ctx,symbol);continue
            if pair['state'] in ('ABORT','CLOSING'):self._cleanup(ctx,symbol);continue
            if pair['state']=='HOLDING':
                basket=pair['basket'];reason=None
                if ctx.now-basket['submitted_at']>=HORIZON:reason='maximum_hold'
                elif decision:
                    values=self._values(row,symbol)
                    if values is None:reason='invalid_or_stale_feature'
                    else:
                        rb,pb=values['binance'];ry,py=values['bybit'];directed=basket['direction']*(ry-rb)
                        forecast=basket['quantity']*(pb+py)/2*directed*168
                        if directed<=0:reason='differential_reversal'
                        elif forecast<.5*basket['entry_cost']:reason='carry_decay'
                if reason:self._begin_close(ctx,symbol,reason)
                continue
            if not decision or ctx.now>=self.stop-HORIZON or (pair['cooldown'] is not None and ctx.now<pair['cooldown']):continue
            if not self._flat(ctx,symbol):self._abort_pair(ctx,symbol,'unexpected_inventory');continue
            basket,reason=self._admission(ctx,symbol,row)
            if basket is None:
                self._log(ctx,'ADMISSION_REJECTED',symbol=symbol,reason=reason);continue
            self._start(ctx,symbol,basket)

CrossVenueFundingCarry=CrossVenueCarry
