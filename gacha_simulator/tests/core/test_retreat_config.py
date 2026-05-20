import pytest
from gacha_simulator.core.config_store import (
    ConfigStore, PoolEntry, PityConfig, PityDef, GainRule, DayOverride,
    TargetCardEntry, CardDefEntry,
)
from gacha_simulator.core.retreat_config import RetreatConfigBuilder


def _make_store_with_3_pools():
    store = ConfigStore()
    store.pools = [
        PoolEntry(pool_id='pool_1', name='池1', start_day=0, end_day=21),
        PoolEntry(pool_id='pool_2', name='池2', start_day=21, end_day=42),
        PoolEntry(pool_id='pool_3', name='池3', start_day=42, end_day=63),
    ]
    store.pity = PityConfig(enabled=True, pities=[
        PityDef(name='soft_pity', btype='soft', params={'start': '74', 'end': '90'}),
    ])
    store.gain_rules = [
        GainRule(rule_type='every_n_days', param='1', gains={'draw_resource': 100}),
    ]
    store.day_overrides = [
        DayOverride(day=5, gains={'draw_resource': 500}),
        DayOverride(day=30, gains={'draw_resource': 1000}),
        DayOverride(day=50, gains={'draw_resource': 2000}),
        DayOverride(day=70, gains={'draw_resource': 3000}),
    ]
    store.initial_resources = {'draw_resource': 30000}
    store.target_cards = [
        TargetCardEntry(card_id='card_a', quantity=1),
        TargetCardEntry(card_id='card_b', quantity=1),
    ]
    store.card_defs = [
        CardDefEntry(card_id='card_a', name='A', rarity='SSR', pools=['pool_1', 'pool_2']),
        CardDefEntry(card_id='card_b', name='B', rarity='SSR', pools=['pool_3']),
    ]
    return store


def test_truncate_removes_earlier_pools():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    pool_ids = [p.pool_id for p in truncated.pools]
    assert 'pool_1' not in pool_ids
    assert 'pool_2' not in pool_ids
    assert 'pool_3' in pool_ids
    assert len(truncated.pools) == 1


def test_truncate_offsets_pool_days():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    pool_3 = truncated.pools[0]
    assert pool_3.start_day == 0
    assert pool_3.end_day == 21


def test_truncate_sets_initial_resources():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    assert truncated.initial_resources == {'draw_resource': 5000}


def test_truncate_sets_pity_counter_init():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    assert truncated.pity.counter_init == {'soft_pity': 30}


def test_truncate_offsets_day_overrides():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    override_days = [o.day for o in truncated.day_overrides]
    assert 5 not in override_days
    assert 8 in override_days
    assert 28 in override_days


def test_truncate_preserves_gain_rules():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    assert len(truncated.gain_rules) == 1
    assert truncated.gain_rules[0].rule_type == 'every_n_days'


def test_truncate_preserves_target_cards():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    tc_ids = [tc.card_id for tc in truncated.target_cards]
    assert 'card_a' in tc_ids
    assert 'card_b' in tc_ids


def test_truncate_preserves_card_defs():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    cd_ids = [cd.card_id for cd in truncated.card_defs]
    assert 'card_a' in cd_ids
    assert 'card_b' in cd_ids


def test_truncate_invalid_pool_raises():
    store = _make_store_with_3_pools()
    with pytest.raises(ValueError):
        RetreatConfigBuilder.build(
            original_store=store,
            from_pool_id='nonexistent',
            initial_resources={'draw_resource': 5000},
            pity_counter_init={},
        )
