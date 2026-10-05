from dataclasses import replace
from decimal import Decimal
import pytest
from aster.backtest.models import Instrument
from examples.cross_venue.units import common_native_step, bounded_pair_quantity


def pair(step_a=.03, step_b=.02):
    a = Instrument('binance:perpetual:XUSDT', 'binance', 'XUSDT', market_type='perpetual', base='X', lot_size=step_a, min_quantity=step_a)
    b = replace(a, id='bybit:perpetual:XUSDT', exchange='bybit', lot_size=step_b, min_quantity=step_b)
    return a, b


def test_intersection_uses_common_multiples_not_larger_increment():
    a, b = pair()
    assert common_native_step(a, b) == Decimal('.06')
    assert bounded_pair_quantity(.119999, a, b) == .06
    assert bounded_pair_quantity(.12, a, b) == .12


def test_decimal_native_grid_has_no_binary_rounding_up():
    a, b = pair(.001, .01)
    assert common_native_step(a, b) == Decimal('.01')
    assert bounded_pair_quantity(.029999999999, a, b) == .02
    assert bounded_pair_quantity(.03, a, b) == .03


def test_minimum_of_either_venue_blocks_opening():
    a, b = pair()
    b = replace(b, min_quantity=.1)
    assert bounded_pair_quantity(.1, a, b) == 0
    assert bounded_pair_quantity(.12, a, b) == .12


def test_native_pepe_bundle_grid_is_never_rescaled():
    a, b = pair(1, 100)
    a, b = [replace(s, base='1000PEPE', symbol='1000PEPEUSDT') for s in (a, b)]
    assert common_native_step(a, b) == Decimal(100)
    assert bounded_pair_quantity(199, a, b) == 100


@pytest.mark.parametrize('change', [dict(exchange='binance'), dict(base='OTHER'), dict(quote='USDC'), dict(market_type='spot')])
def test_incompatible_legs_rejected(change):
    a, b = pair()
    with pytest.raises(ValueError):
        common_native_step(a, replace(b, **change))


@pytest.mark.parametrize('value', [-1, float('inf'), float('nan')])
def test_invalid_quantity_rejected(value):
    a, b = pair()
    with pytest.raises(ValueError):
        bounded_pair_quantity(value, a, b)
