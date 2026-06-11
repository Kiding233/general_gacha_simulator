from gacha_simulator.core.retreat_search import RetreatSearchEngine, RetreatSearchResult, RetreatSearchPoint


def test_search_result_dataclass():
    result = RetreatSearchResult(
        from_pool_id='pool_2',
        base_resource=5000.0,
        pity_init={'soft_pity': 30},
        search_mode='resource',
        points=[
            RetreatSearchPoint(extra_resource=12000.0, target_specs={'card_a': 1}, success_probability=0.96),
        ],
    )
    assert result.from_pool_id == 'pool_2'
    assert result.base_resource == 5000.0
    assert len(result.points) == 1
    assert result.points[0].extra_resource == 12000.0


def test_engine_init():
    from gacha_simulator.core.config_store import ConfigStore
    store = ConfigStore()
    engine = RetreatSearchEngine(
        config_store=store,
        from_pool_id='pool_1',
        base_resource=5000.0,
        pity_counter_init={'soft_pity': 0},
    )
    assert engine.from_pool_id == 'pool_1'
    assert engine.base_resource == 5000.0


def test_engine_stop():
    from gacha_simulator.core.config_store import ConfigStore
    store = ConfigStore()
    engine = RetreatSearchEngine(
        config_store=store,
        from_pool_id='pool_1',
        base_resource=5000.0,
        pity_counter_init={},
    )
    engine.stop()
    assert engine._should_stop is True
