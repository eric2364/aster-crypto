import math

def floor_step(value, step): return math.floor((value+step*1e-9)/step)*step

def adverse_price(reference, side, spec, config, quantity, prior_bar):
    bps = config.slippage_bps
    if config.slippage_model == 'spread': bps += config.spread_bps/2
    elif config.slippage_model == 'volatility' and prior_bar is not None:
        bps += config.impact_bps*(prior_bar['high']-prior_bar['low'])/prior_bar['close']
    elif config.slippage_model == 'volume':
        volume = prior_bar['volume'] if prior_bar else 0
        bps += config.impact_bps*quantity/max(volume,quantity)
    raw = reference*(1+side*bps/10000)
    if not math.isfinite(raw) or raw <= 0: raise ValueError('Nonpositive or nonfinite execution price')
    ticks = raw/spec.tick_size
    price = (math.ceil(ticks-1e-10) if side>0 else math.floor(ticks+1e-10))*spec.tick_size
    if price <= 0: raise ValueError('Nonpositive execution price after tick rounding')
    return price
