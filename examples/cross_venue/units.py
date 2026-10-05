"""Exact common native grids for two distinct linear-USDT venue legs."""
from decimal import Decimal, localcontext
from fractions import Fraction
import math


def _positive(value, name):
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError(f'{name} must be finite and positive')
    return result


def common_native_step(first, second):
    """Intersection of native quantity grids; bundle units remain native."""
    if (first.exchange == second.exchange or first.id == second.id
            or first.base != second.base or first.quote != second.quote
            or first.quote != 'USDT'
            or any(s.market_type != 'perpetual' or s.contract_type != 'linear'
                   or s.multiplier != 1 for s in (first, second))):
        raise ValueError('Require matching native-base linear USDT contracts on distinct venues')
    steps = [Fraction(_positive(s.lot_size, 'lot_size')) for s in (first, second)]
    denominator = math.lcm(*(s.denominator for s in steps))
    numerators = [s.numerator * (denominator // s.denominator) for s in steps]
    numerator = math.lcm(*numerators)
    with localcontext() as context:
        context.prec = len(str(numerator)) + len(str(denominator)) + 10
        return Decimal(numerator) / Decimal(denominator)


def bounded_pair_quantity(ideal, first, second):
    """Floor equal native quantities, returning zero below either opening minimum.

    Notional minima and available venue collateral require prices and are checked
    separately by the coordinator. This utility does not promise acceptance.
    """
    step = common_native_step(first, second)
    value = Decimal(str(ideal))
    if not value.is_finite() or value < 0:
        raise ValueError('Ideal quantity must be finite and nonnegative')
    grid = Fraction(step)
    rounded = (Fraction(value) // grid) * grid
    if rounded < max(Fraction(_positive(s.min_quantity, 'min_quantity')) for s in (first, second)):
        return 0.0
    result = float(rounded)
    if not math.isfinite(result):
        raise ValueError('Native quantity exceeds finite Engine range')
    return result
