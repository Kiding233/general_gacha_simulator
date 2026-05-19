import pytest
from gacha_simulator.service.batch_service import (
    BatchService, BatchConfig, SimulationVariant, ConditionGenerator
)
from gacha_simulator.service.gacha_service import GachaService
from gacha_simulator.core import GachaState, Pool, Reward, Strategy, StopCondition, TargetCardSet
from gacha_simulator.core.action import DrawAction, WaitAction


class DummyStrategy(Strategy):
    lookahead = None
    @classmethod
    def description(cls): return "Dummy"
    def select_action(self, state, history, pools, futures, targets, stop):
        if len(history) >= 5:
            return WaitAction(0)
        return DrawAction('test')


class DummyStop(StopCondition):
    def check(self, state, history): return len(history) >= 5
    def description(self): return ""


def create_service_factory():
    pool = Pool('test', 'Test', {'gem': 10}, [(Reward('a', 'A'), 0.5), (Reward('b', 'B'), 0.5)])
    def factory() -> GachaService:
        return GachaService([pool], DummyStrategy(), DummyStop(), TargetCardSet([]))
    return factory


def test_batch_service_run():
    service = BatchService(create_service_factory())
    variant = SimulationVariant(
        name="test",
        initial_state_fn=lambda: GachaState(resources={'gem': 100}),
    )
    results = service.run_batch([variant], BatchConfig(simulations_per_variant=5))
    assert len(results) == 1
    assert results[0].total_simulations == 5
    assert len(results[0].histories) == 5


def test_condition_generator_fixed():
    variant = ConditionGenerator.fixed_state({'gem': 1000}, {'ssr': 50})
    state = variant.initial_state_fn()
    assert state.resources['gem'] == 1000
    assert state.pity_counters['ssr'] == 50


def test_condition_generator_random():
    variant = ConditionGenerator.random_resources({'gem': (0, 1000)})
    states = [variant.initial_state_fn() for _ in range(100)]
    gem_values = [s.resources['gem'] for s in states]
    assert min(gem_values) >= 0
    assert max(gem_values) <= 1000
