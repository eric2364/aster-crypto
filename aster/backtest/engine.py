"""Deterministic interval-boundary simulator. See docs/execution_model.md."""
from dataclasses import dataclass
from collections import defaultdict
import math
import pandas as pd
from aster.backtest.models import Order
from aster.backtest.portfolio import Portfolio, EPS
from aster.backtest.execution import adverse_price, floor_step
from aster.data.validation import normalize_bars, normalize_funding

@dataclass
class Result:
    equity: pd.DataFrame
    fills: pd.DataFrame
    trades: pd.DataFrame
    funding: pd.DataFrame
    events: pd.DataFrame
    positions: pd.DataFrame
    quality: dict
    config: object
    instruments: list
    strategy: str
    strategy_version: str = '1'

class Context:
    def __init__(self, engine): self._engine = engine
    @property
    def now(self): return self._engine.now
    @property
    def positions(self): return self._engine.portfolio.positions
    @property
    def instruments(self): return self._engine.instruments
    @property
    def portfolio(self): return self._engine.portfolio
    def history(self, iid, count=None):
        rows = self._engine.history[iid]
        return pd.DataFrame(rows[-count:] if count else rows).copy()
    def order(self, order): return self._engine.submit(order)
    def cancel(self, order_id): self._engine.cancel(order_id)
    def target(self, iid, quantity):
        # Replace pending target orders to avoid building an accidental order backlog.
        for o in list(self._engine.orders.values()):
            if o.instrument_id == iid and o.status in ('accepted','partial'): self.cancel(o.id)
        diff = quantity-self.positions[iid].quantity
        spec = self.instruments[iid]
        qty = floor_step(abs(diff),spec.lot_size)
        if qty >= spec.min_quantity-EPS:
            return self.order(Order(iid,1 if diff>0 else -1,qty,
                reduce_only=quantity==0 and spec.market_type=='perpetual'))

class Engine:
    def __init__(self, instruments, config):
        if len({s.id for s in instruments}) != len(instruments): raise ValueError('Duplicate instrument IDs')
        self.instruments = {s.id:s for s in instruments}
        self.config = config
        self.portfolio = Portfolio(instruments,config)
        self.orders = {}
        self.history = defaultdict(list)
        self.prior = {}
        self.now = None
        self.context = Context(self)
        self._started = False
        self._sequence = 0
        self._used = defaultdict(float)
        self._duration = {}

    def submit(self, order):
        if self.now is None: raise RuntimeError('Orders require an event callback')
        if order.instrument_id not in self.instruments: raise ValueError('Unknown instrument')
        s = self.instruments[order.instrument_id]
        self._sequence += 1
        order.id = f'O{self._sequence:08d}'
        order.submitted_at = self.now
        delay = pd.Timedelta(milliseconds=self.config.latency_ms) + pd.Timedelta(
            seconds=self.config.execution_delay_bars*self._duration.get(s.id,60))
        order.active_at = self.now+delay
        order.remaining = order.quantity
        self.portfolio.event('ORDER_SUBMITTED',self.now,s.id,order_id=order.id,side=order.side,
            quantity=order.quantity,order_type=order.order_type,limit_price=order.limit_price,stop_price=order.stop_price,
            active_at=order.active_at,tif=order.tif,post_only=order.post_only,reduce_only=order.reduce_only)
        reason = ''
        if order.side not in (-1,1) or not math.isfinite(order.quantity) or order.quantity <= 0: reason='invalid_quantity_or_side'
        elif order.quantity < s.min_quantity-EPS or abs(order.quantity/s.lot_size-round(order.quantity/s.lot_size)) > 1e-6: reason='lot_size'
        elif order.order_type not in ('market','limit','stop_market','stop_limit') or order.tif not in ('GTC','IOC','FOK'): reason='unsupported_order'
        elif order.post_only and order.order_type not in ('limit','stop_limit'): reason='post_only_requires_limit'
        elif order.reduce_only and s.market_type=='spot': reason='reduce_only_requires_perpetual'
        for name,required in [('limit_price',order.order_type in ('limit','stop_limit')),('stop_price',order.order_type in ('stop_market','stop_limit'))]:
            value = getattr(order,name)
            if required and (value is None or not math.isfinite(value) or value<=0): reason='invalid_'+name
            elif value is not None and abs(value/s.tick_size-round(value/s.tick_size))>1e-6: reason='tick_size'
        if reason:
            order.status = 'rejected'
            self.portfolio.event('ORDER_REJECTED',self.now,s.id,order_id=order.id,reason=reason)
        else:
            order.status = 'accepted'
            self.orders[order.id] = order
            self.portfolio.event('ORDER_ACCEPTED',self.now,s.id,order_id=order.id)
        return order.id

    def cancel(self, oid, reason='strategy'):
        order = self.orders.get(oid)
        if order and order.status in ('accepted','partial'):
            order.status = 'cancelled'
            self.portfolio.event('ORDER_CANCELLED',self.now,order.instrument_id,order_id=oid,reason=reason)
            self.orders.pop(oid,None)

    def _eligible(self, iid):
        return [o for o in self.orders.values() if o.instrument_id==iid and o.status in ('accepted','partial') and o.active_at<=self.now]

    def _fill(self, order, reference, liquidity, capacity, timestamp):
        s = self.instruments[order.instrument_id]
        p = self.portfolio.positions[s.id]
        qty = floor_step(min(order.remaining,max(0,capacity)),s.lot_size)
        if order.reduce_only:
            if p.quantity*order.side >= 0:
                self.cancel(order.id,'reduce_only_no_position'); return 0
            qty = min(qty,abs(p.quantity))
        if order.tif=='FOK' and qty+EPS < order.remaining:
            self.cancel(order.id,'fok_capacity'); return 0
        if qty < s.min_quantity-EPS: return 0
        price = reference if liquidity=='maker' else adverse_price(reference,order.side,s,self.config,qty,self.prior.get(s.id))
        if order.limit_price is not None and order.order_type in ('limit','stop_limit'):
            if (price-order.limit_price)*order.side > EPS: return 0
        if qty*price < s.min_notional-EPS:
            if not order.reduce_only: return 0
        ok,reason = self.portfolio.apply_fill(s.id,order.side,qty,price,timestamp,liquidity,order.order_type,
            reference_price=reference,order_id=order.id)
        if not ok:
            self.cancel(order.id,'risk_'+reason); return 0
        order.remaining = max(0,order.remaining-qty)
        order.status = 'filled' if order.remaining<EPS else 'partial'
        if order.status=='filled': self.orders.pop(order.id,None)
        self.portfolio.event('ORDER_FILLED' if order.status=='filled' else 'ORDER_PARTIALLY_FILLED',
            timestamp,s.id,order_id=order.id,quantity=qty,price=price,liquidity_type=liquidity)
        return qty

    def _open(self, bar):
        iid = bar['instrument_id']
        s = self.instruments[iid]
        self._duration[iid] = bar['duration_seconds']
        # Capacity uses only previously completed volume, never this bar's future volume.
        capacity = self.prior.get(iid,{}).get('volume',0)*self.config.participation
        self._used[(iid,bar['timestamp'])] = 0.0
        for order in self._eligible(iid):
            first = order.first_seen is None
            if first: order.first_seen = bar['timestamp']
            if order.order_type in ('stop_market','stop_limit') and not order.triggered:
                hit = order.side*(bar['open']-order.stop_price)>=0
                if hit:
                    order.triggered=True
                    first=True
                    order.first_seen=bar['timestamp']
                else:
                    if order.tif!='GTC': self.cancel(order.id,'conditional_not_triggered')
                    continue
            kind = order.order_type
            if kind=='stop_market' and order.triggered: kind='market'
            if kind=='stop_limit' and order.triggered: kind='limit'
            marketable = kind=='market' or (kind=='limit' and order.side*(bar['open']-order.limit_price)<=0)
            if first and order.post_only and marketable:
                self.cancel(order.id,'post_only_cross'); continue
            if marketable:
                # Previously resting limits crossing at open receive own price as maker;
                # newly activated crossing orders are taker, including triggered stop-limits.
                maker = kind=='limit' and not first and order.first_seen<bar['timestamp']
                reference = order.limit_price if maker else bar['open']
                qty = self._fill(order,reference,'maker' if maker else 'taker',capacity,self.now)
                capacity -= qty
                self._used[(iid,bar['timestamp'])] += qty
            if order.tif in ('IOC','FOK') and order.status in ('accepted','partial'):
                self.cancel(order.id,'immediate_remainder')

    def _close(self, bar):
        iid = bar['instrument_id']
        s = self.instruments[iid]
        capacity = max(0,bar['volume']*self.config.participation-self._used[(iid,bar['timestamp'])])
        for order in self._eligible(iid):
            # It must have been active at the opening of this interval.
            if order.active_at > bar['timestamp'] or order.first_seen is None: continue
            if order.order_type in ('stop_market','stop_limit') and not order.triggered:
                hit = bar['high']>=order.stop_price if order.side>0 else bar['low']<=order.stop_price
                if hit:
                    order.triggered=True
                    order.active_at=self.now+pd.Timedelta(milliseconds=self.config.latency_ms)
                    order.first_seen=None
                    self.portfolio.event('STOP_TRIGGERED',self.now,iid,order_id=order.id)
                continue
            if order.order_type not in ('limit','stop_limit'): continue
            if order.order_type=='stop_limit' and not order.triggered: continue
            # Conservative: one full resting interval + strict trade-through by one tick.
            conservative = self.config.fill_model in ('conservative','volume_aware')
            if conservative and order.first_seen >= bar['timestamp']: continue
            threshold = order.limit_price - s.tick_size if order.side>0 else order.limit_price+s.tick_size
            hit = (bar['low'] < threshold if order.side>0 else bar['high'] > threshold) if conservative else (
                bar['low']<=order.limit_price if order.side>0 else bar['high']>=order.limit_price)
            if hit:
                qty = self._fill(order,order.limit_price,'maker',capacity,self.now)
                capacity -= qty
        self.prior[iid] = bar

    def _liquidate(self):
        ids = self.portfolio.liquidation_candidates()
        for iid in ids:
            p = self.portfolio.positions[iid]
            for order in list(self.orders.values()):
                if order.instrument_id==iid: self.cancel(order.id,'liquidation')
            s = self.instruments[iid]
            reference = self.portfolio.marks[iid]
            side = -1 if p.quantity>0 else 1
            price = adverse_price(reference,side,s,self.config,abs(p.quantity),self.prior.get(iid))
            self.portfolio.event('MARGIN_WARNING',self.now,iid)
            self.portfolio.apply_fill(iid,side,abs(p.quantity),price,self.now,'taker','market',reference,
                exit_reason='liquidation',forced=True)
            self.portfolio.event('LIQUIDATION',self.now,iid,mark_price=reference,execution_price=price,
                cash_after=self.portfolio.cash[s.exchange])
        # Negative balances remain visible. No artificial insurance-fund credit.

    def run(self, bars, strategy, funding=None):
        if self._started: raise RuntimeError('Engine instances are single use')
        self._started=True
        bars,quality = normalize_bars(bars,self.instruments)
        funding = normalize_funding(funding,self.instruments)
        start,end = bars.timestamp.min(),bars.end.max()
        funding = funding[(funding.timestamp>=start)&(funding.timestamp<=end)]
        events = defaultdict(lambda:{'open':[],'close':[],'funding':[]})
        for row in bars.to_dict('records'):
            events[row['timestamp']]['open'].append(row)
            events[row['end']]['close'].append(row)
        if self.config.funding_enabled:
            for row in funding.to_dict('records'): events[row['timestamp']]['funding'].append(row)
        else: quality.warnings.append('Funding disabled explicitly')
        perps = [i for i in bars.instrument_id.unique() if self.instruments[i].market_type=='perpetual']
        for iid in perps:
            if 'mark_price' not in bars or 'mark_open' not in bars:
                quality.warnings.append(f'{iid}: trade prices proxy missing mark observations; intrabar mark risk unavailable')
            if self.config.funding_enabled and iid not in set(funding.instrument_id):
                quality.warnings.append(f'{iid}: no historical funding settlements supplied; funding omitted, coverage unverified')
        snapshots = []
        for n,t in enumerate(sorted(events)):
            self.now=t
            ev=events[t]
            if n==0: snapshots.append(self.portfolio.snapshot(t))
            # A simultaneous market slice is atomic for account-wide risk.
            for bar in ev['close']:
                self.portfolio.marks[bar['instrument_id']] = bar.get('mark_price',bar['close'])
            for bar in ev['close']: self._close(bar)
            self._liquidate()
            for settlement in ev['funding']:
                self.portfolio.marks[settlement['instrument_id']] = float(settlement['mark_price'])
            self._liquidate()
            for settlement in ev['funding']:
                self.portfolio.settle_funding(settlement)
            self._liquidate()
            # Every strategy sees the complete simultaneous close slice.
            for bar in ev['close']: self.history[bar['instrument_id']].append(bar.copy())
            for settlement in ev['funding']: strategy.on_funding(self.context,settlement.copy())
            for bar in ev['close']: strategy.on_bar(self.context,bar.copy())
            if ev['close']: strategy.on_bars(self.context,[b.copy() for b in ev['close']])
            for bar in ev['open']:
                self.portfolio.marks[bar['instrument_id']] = bar.get('mark_open',bar['open'])
            self._liquidate()
            for bar in ev['open']: self._open(bar)
            self._liquidate()
            if n>0 and (n % self.config.record_every==0 or t==end): snapshots.append(self.portfolio.snapshot(t))
        for order in list(self.orders.values()):
            if order.status in ('accepted','partial'): self.cancel(order.id,'end_of_data')
        positions=[]
        for iid,p in self.portfolio.positions.items():
            if abs(p.quantity)>EPS:
                s=self.instruments[iid]
                positions.append({'instrument_id':iid,'exchange':s.exchange,'symbol':s.symbol,'quantity':p.quantity,
                    'average_price':p.average_price,'mark_price':self.portfolio.marks.get(iid),'unrealized_pnl':self.portfolio.unrealized(iid),
                    'funding_pnl':p.funding,'entry_fees':p.maker_fees+p.taker_fees,'collateral':p.collateral,
                    'liquidation_price':self.portfolio.liquidation_price(iid),
                    'maintenance_margin':abs(p.quantity)*self.portfolio.marks.get(iid,p.average_price)*s.maintenance_rate if s.market_type=='perpetual' else 0})
        # Keep the initial baseline at duplicate start time: metrics handle it explicitly.
        return Result(pd.DataFrame(snapshots),pd.DataFrame(self.portfolio.fills),pd.DataFrame(self.portfolio.trades),
            pd.DataFrame(self.portfolio.funding),pd.DataFrame(self.portfolio.events),pd.DataFrame(positions),
            quality.to_dict(),self.config,list(self.instruments.values()),type(strategy).__name__,str(getattr(strategy,'version','unversioned')))
