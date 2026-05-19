import pytest
from gacha_simulator.core.resource_gain import (
    LinearResourceGain, PeriodicResourceGain, CompositeResourceGain
)
from gacha_simulator.core.state import GachaState


def test_linear_gain():
    func = LinearResourceGain({'draw_resource': 10, 'mora': 100})
    gains = func.compute(60, GachaState())
    assert gains['draw_resource'] == 600
    assert gains['mora'] == 6000


def test_periodic_gain():
    func = PeriodicResourceGain(period=3600, reward={'daily': 600})
    gains = func.compute(3600, GachaState())
    assert gains['daily'] == 600
    gains = func.compute(7199, GachaState())
    assert gains['daily'] == 600
    gains = func.compute(7200, GachaState())
    assert gains['daily'] == 1200


def test_composite_gain():
    linear = LinearResourceGain({'draw_resource': 1})
    periodic = PeriodicResourceGain(10, {'bonus': 100})
    composite = CompositeResourceGain([linear, periodic])
    gains = composite.compute(10, GachaState())
    assert gains['draw_resource'] == 10
    assert gains['bonus'] == 100
