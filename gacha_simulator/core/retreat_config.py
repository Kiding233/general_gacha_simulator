from typing import Dict
from .config_store import ConfigStore, PoolEntry, PityConfig, PityDef, GainRule, DayOverride, TargetCardEntry, CardDefEntry, PoolDistEntry


class RetreatConfigBuilder:
    @staticmethod
    def build(
        original_store: ConfigStore,
        from_pool_id: str,
        initial_resources: Dict[str, float],
        pity_counter_init: Dict[str, int],
    ) -> ConfigStore:
        from_pool = None
        for p in original_store.pools:
            if p.pool_id == from_pool_id:
                from_pool = p
                break

        if from_pool is None:
            raise ValueError(f"Pool '{from_pool_id}' not found in config")

        offset_day = from_pool.end_day if from_pool.end_day > 0 else (from_pool.start_day + 21)

        truncated = ConfigStore()

        truncated.pools = []
        for p in original_store.pools:
            if p.start_day >= offset_day:
                truncated.pools.append(PoolEntry(
                    enabled=p.enabled,
                    pool_id=p.pool_id,
                    name=p.name,
                    start_day=p.start_day - offset_day,
                    end_day=p.end_day - offset_day,
                    cost=p.cost,
                    distribution_file=p.distribution_file,
                    bindings=dict(p.bindings),
                    target_specs=list(p.target_specs),
                    rerun_of=p.rerun_of,
                    exchange_card_id=p.exchange_card_id,
                    distribution=[PoolDistEntry(
                        card_id=d.card_id,
                        probability=d.probability,
                        rarity=d.rarity,
                        featured=d.featured,
                        resources_gained=dict(d.resources_gained),
                    ) for d in p.distribution],
                ))

        truncated.pity = PityConfig(
            enabled=original_store.pity.enabled,
            pities=[PityDef(
                name=pd.name,
                btype=pd.btype,
                params=dict(pd.params),
                target_distribution=dict(pd.target_distribution),
                reset_condition=pd.reset_condition,
                pools=pd.pools,
            ) for pd in original_store.pity.pities],
            counter_init=dict(pity_counter_init),
        )

        truncated.initial_resources = dict(initial_resources)

        truncated.gain_rules = [
            GainRule(
                rule_type=gr.rule_type,
                param=gr.param,
                gains=dict(gr.gains),
            )
            for gr in original_store.gain_rules
        ]

        truncated.day_overrides = []
        for dor in original_store.day_overrides:
            new_day = dor.day - offset_day
            if new_day >= 0:
                truncated.day_overrides.append(DayOverride(
                    day=new_day,
                    gains=dict(dor.gains),
                ))

        remaining_pool_ids = {p.pool_id for p in truncated.pools}
        available_card_ids = {cd.card_id for cd in original_store.card_defs
                             if set(cd.pools) & remaining_pool_ids}

        truncated.target_cards = [
            TargetCardEntry(
                card_id=tc.card_id,
                quantity=tc.quantity,
                pool_ids=list(tc.pool_ids),
            )
            for tc in original_store.target_cards
            if tc.card_id in available_card_ids
        ]

        truncated.card_defs = [
            CardDefEntry(
                card_id=cd.card_id,
                name=cd.name,
                rarity=cd.rarity,
                pools=list(cd.pools),
            )
            for cd in original_store.card_defs
            if set(cd.pools) & remaining_pool_ids
        ]

        truncated.resource_defs = dict(original_store.resource_defs)
        truncated.strategy_type = original_store.strategy_type
        truncated.auto_wait = original_store.auto_wait

        return truncated
