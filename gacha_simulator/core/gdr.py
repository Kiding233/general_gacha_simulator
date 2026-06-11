from typing import List, Dict, Set, Optional, Callable, Any, NamedTuple, Union
from dataclasses import dataclass, field

from .result_types import CompactResult


@dataclass
class GDRContext:
    target_specs: Dict[str, int]
    ssr_ids: Set[str]
    all_drawable_ids: List[str]
    initial_resources: Dict[str, float]
    resource_gain_per_day: Dict[str, float]
    collection_sets: Dict[str, Set[str]] = field(default_factory=dict)
    weapon_character_map: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 兼容的 dict。Set 类型字段转为 list。"""
        return {
            'target_specs': dict(self.target_specs),
            'ssr_ids': list(self.ssr_ids),
            'all_drawable_ids': list(self.all_drawable_ids),
            'initial_resources': dict(self.initial_resources),
            'resource_gain_per_day': dict(self.resource_gain_per_day),
            'collection_sets': {k: list(v) for k, v in self.collection_sets.items()},
            'weapon_character_map': dict(self.weapon_character_map),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'GDRContext':
        """从 dict 反序列化。list 字段转回 set。"""
        return cls(
            target_specs={str(k): int(v) for k, v in d.get('target_specs', {}).items()},
            ssr_ids=set(d.get('ssr_ids', [])),
            all_drawable_ids=[str(x) for x in d.get('all_drawable_ids', [])],
            initial_resources={str(k): float(v) for k, v in d.get('initial_resources', {}).items()},
            resource_gain_per_day={str(k): float(v) for k, v in d.get('resource_gain_per_day', {}).items()},
            collection_sets={str(k): set(v) for k, v in d.get('collection_sets', {}).items()},
            weapon_character_map={str(k): str(v) for k, v in d.get('weapon_character_map', {}).items()},
        )


class WeightedGDRConfig:
    def __init__(self, weight_config, scheme_map: Dict[str, str] = None):
        self.weight_config = weight_config
        self.scheme_map = scheme_map or {}

    def get_weight_function(self, gdr_name: str) -> Callable[[str], float]:
        scheme = self.scheme_map.get(gdr_name, 'default')
        return self.weight_config.create_weight_function(scheme)


def _count_draws(history) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for iv in history:
        if iv.action_type == 'draw' and iv.card_id:
            counts[iv.card_id] = counts.get(iv.card_id, 0) + 1
    return counts


def _total_resource_consumed(history, resource: str = 'draw_resource') -> float:
    total = 0.0
    for iv in history:
        if iv.action_type == 'draw':
            total += iv.resources_consumed.get(resource, 0)
    return total


def _total_resource_gained(history, resource: str = 'draw_resource') -> float:
    total = 0.0
    for iv in history:
        total += iv.resources_gained.get(resource, 0)
    return total


def simple_target_achievement_rate(history, ctx: GDRContext) -> float:
    if not ctx.target_specs:
        return 0.0
    counts = _count_draws(history)
    achieved = 0
    total = 0
    for card_id, qty in ctx.target_specs.items():
        got = min(counts.get(card_id, 0), qty)
        achieved += got
        total += qty
    return achieved / total if total > 0 else 0.0


def weighted_target_achievement_rate(history, ctx: GDRContext, get_weight: Callable[[str], float]) -> float:
    if not ctx.target_specs:
        return 0.0
    counts = _count_draws(history)
    weighted_achieved = 0.0
    total_weight = 0.0
    for card_id, qty in ctx.target_specs.items():
        weight = get_weight(card_id)
        got = min(counts.get(card_id, 0), qty)
        weighted_achieved += got * weight
        total_weight += qty * weight
    return weighted_achieved / total_weight if total_weight > 0 else 0.0


def all_targets_obtained(history, ctx: GDRContext) -> float:
    if not ctx.target_specs:
        return 1.0
    counts = _count_draws(history)
    for card_id, qty in ctx.target_specs.items():
        if counts.get(card_id, 0) < qty:
            return 0.0
    return 1.0


def ssr_collection_rate(history, ctx: GDRContext) -> float:
    return card_collection_rate(history, ctx, 'SSR', ctx.ssr_ids)


def weighted_collection_rate(history, ctx: GDRContext, get_weight: Callable[[str], float], card_set: Optional[Set[str]] = None) -> float:
    if not card_set:
        return 0.0
    counts = _count_draws(history)
    weighted_obtained = 0.0
    total_weight = 0.0
    for card_id in card_set:
        weight = get_weight(card_id)
        total_weight += weight
        if counts.get(card_id, 0) > 0:
            weighted_obtained += weight
    return weighted_obtained / total_weight if total_weight > 0 else 0.0


def card_collection_rate(history, ctx: GDRContext, collection_name: str, card_set: Optional[Set[str]] = None) -> float:
    if card_set is None:
        card_set = ctx.collection_sets.get(collection_name, set())
    if not card_set:
        return 0.0
    counts = _count_draws(history)
    unique_obtained = set()
    for card_id, cnt in counts.items():
        if card_id in card_set and cnt > 0:
            unique_obtained.add(card_id)
    return len(unique_obtained) / len(card_set)


def resource_remaining(history, ctx: GDRContext, resource: str = 'draw_resource') -> float:
    initial = ctx.initial_resources.get(resource, 0)
    gained = _total_resource_gained(history, resource)
    consumed = _total_resource_consumed(history, resource)
    return initial + gained - consumed


def extra_target_cards(history, ctx: GDRContext) -> float:
    if not ctx.target_specs:
        return 0.0
    counts = _count_draws(history)
    extra = 0
    for card_id, qty in ctx.target_specs.items():
        got = counts.get(card_id, 0)
        if got > qty:
            extra += got - qty
    return float(extra)


def weighted_extra_cards(history, ctx: GDRContext, get_weight: Callable[[str], float]) -> float:
    if not ctx.target_specs:
        return 0.0
    counts = _count_draws(history)
    weighted_extra = 0.0
    for card_id, qty in ctx.target_specs.items():
        got = counts.get(card_id, 0)
        if got > qty:
            weighted_extra += (got - qty) * get_weight(card_id)
    return weighted_extra


def regret_index(history, ctx: GDRContext, get_weight: Callable[[str], float]) -> float:
    if not ctx.target_specs:
        return 0.0
    counts = _count_draws(history)
    regret = 0.0
    for card_id, qty in ctx.target_specs.items():
        got = counts.get(card_id, 0)
        if got < qty:
            regret += (qty - got) * get_weight(card_id)
    return regret


def weighted_satisfaction(history, ctx: GDRContext, get_desire_weight: Callable[[str], float], get_miss_cost: Callable[[str], float]) -> float:
    if not ctx.target_specs:
        return 0.0
    counts = _count_draws(history)
    satisfaction = 0.0
    for card_id, qty in ctx.target_specs.items():
        got = min(counts.get(card_id, 0), qty)
        missed = max(qty - counts.get(card_id, 0), 0)
        satisfaction += got * get_desire_weight(card_id)
        satisfaction -= missed * get_miss_cost(card_id)
    return satisfaction


def total_card_value(history, ctx: GDRContext, get_weight: Callable[[str], float]) -> float:
    counts = _count_draws(history)
    total_value = 0.0
    for card_id, cnt in counts.items():
        total_value += cnt * get_weight(card_id)
    return total_value


def non_pity_draws(history, ctx: GDRContext) -> float:
    count = 0
    for iv in history:
        if iv.action_type == 'draw' and not iv.pity_triggered:
            count += 1
    return float(count)


def pity_draws(history, ctx: GDRContext) -> float:
    count = 0
    for iv in history:
        if iv.action_type == 'draw' and iv.pity_triggered:
            count += 1
    return float(count)


def guaranteed_gdr(history, ctx: GDRContext, gdr_func: Callable, threshold: float) -> float:
    value = gdr_func(history, ctx)
    return 1.0 if value >= threshold else 0.0


def joint_gdr(history, ctx: GDRContext, gdr_results: Dict[str, float], thresholds: Dict[str, float]) -> float:
    for name, threshold in thresholds.items():
        if gdr_results.get(name, 0) < threshold:
            return 0.0
    return 1.0


def resource_efficiency(history, ctx: GDRContext) -> float:
    counts = _count_draws(history)
    target_cards_obtained = sum(
        min(counts.get(card_id, 0), qty)
        for card_id, qty in ctx.target_specs.items()
    )
    total_consumed = _total_resource_consumed(history)
    return target_cards_obtained / total_consumed if total_consumed > 0 else 0.0


def _pool_draw_counts(history) -> Dict[str, int]:
    pool_counts: Dict[str, int] = {}
    for iv in history:
        if iv.action_type == 'draw' and iv.pool_id:
            pool_counts[iv.pool_id] = pool_counts.get(iv.pool_id, 0) + 1
    return pool_counts


def _pool_card_draw_counts(history, card_set: Optional[Set[str]] = None) -> Dict[str, int]:
    pool_card_counts: Dict[str, int] = {}
    for iv in history:
        if iv.action_type == 'draw' and iv.pool_id:
            if card_set is None or iv.card_id in card_set:
                pool_card_counts[iv.pool_id] = pool_card_counts.get(iv.pool_id, 0) + 1
    return pool_card_counts


def per_pool_draw_rate(history, ctx: GDRContext, card_set: Optional[Set[str]] = None) -> float:
    pool_card = _pool_card_draw_counts(history, card_set)
    pool_total = _pool_draw_counts(history)
    pools_with_draws = sum(1 for c in pool_total.values() if c > 0)
    if pools_with_draws == 0:
        return 0.0
    total_card_draws = sum(pool_card.values())
    return total_card_draws / pools_with_draws


def weapon_character_ratio(history, ctx: GDRContext) -> float:
    if not ctx.weapon_character_map:
        return 0.0
    counts = _count_draws(history)
    char_ids = set(ctx.weapon_character_map.values())
    char_count = sum(counts.get(cid, 0) for cid in char_ids)
    if char_count == 0:
        return 0.0
    weapon_count = 0
    for weapon_id, char_id in ctx.weapon_character_map.items():
        if counts.get(char_id, 0) > 0:
            weapon_count += counts.get(weapon_id, 0)
    return weapon_count / char_count


def target_collection_rate(history, ctx: GDRContext) -> float:
    return card_collection_rate(history, ctx, '目标卡', set(ctx.target_specs.keys()))


def _gdr_target_achievement(compact, target_specs, **kwargs):
    card_counts = compact.get('card_counts', {})
    total = sum(target_specs.values())
    if total == 0:
        return 0.0
    achieved = sum(min(card_counts.get(cid, 0), qty) for cid, qty in target_specs.items())
    return achieved / total


def _gdr_target_collection(compact, target_specs, **kwargs):
    card_counts = compact.get('card_counts', {})
    total_kinds = len(target_specs)
    if total_kinds == 0:
        return 0.0
    collected = sum(1 for cid in target_specs if card_counts.get(cid, 0) > 0)
    return collected / total_kinds


def _gdr_all_targets(compact, target_specs, **kwargs):
    card_counts = compact.get('card_counts', {})
    for cid, qty in target_specs.items():
        if card_counts.get(cid, 0) < qty:
            return 0.0
    return 1.0


def _gdr_ssr_collection(compact, target_specs, ssr_ids=None, **kwargs):
    card_counts = compact.get('card_counts', {})
    if not ssr_ids:
        return 0.0
    collected = sum(1 for cid in ssr_ids if card_counts.get(cid, 0) > 0)
    return collected / len(ssr_ids)


def _gdr_resource_remaining(compact, **kwargs):
    final_resources = compact.get('final_resources', {})
    resource_id = kwargs.get('resource_id', 'draw_resource')
    return final_resources.get(resource_id, 0)


def _gdr_extra_target(compact, target_specs, **kwargs):
    card_counts = compact.get('card_counts', {})
    if not target_specs:
        return 0.0
    extra = 0
    for cid, qty in target_specs.items():
        got = card_counts.get(cid, 0)
        if got > qty:
            extra += got - qty
    return float(extra)


def _gdr_non_pity_draws(compact, **kwargs):
    total_draws = compact.get('total_draws', 0)
    pity_triggers = compact.get('pity_triggers', 0)
    return float(total_draws - pity_triggers)


def _gdr_pity_draws(compact, **kwargs):
    return float(compact.get('pity_triggers', 0))


def _gdr_resource_efficiency(compact, target_specs, **kwargs):
    card_counts = compact.get('card_counts', {})
    total_consumed = compact.get('total_consumed', {})
    achieved = sum(min(card_counts.get(cid, 0), qty) for cid, qty in target_specs.items())
    resource_id = kwargs.get('resource_id', 'draw_resource')
    consumed = total_consumed.get(resource_id, 0)
    return achieved / consumed if consumed > 0 else 0.0


def _gdr_per_pool_draw_rate(compact, target_specs, **kwargs):
    pool_draw_counts = compact.get('pool_draw_counts', {})
    pool_card_counts = compact.get('pool_card_counts', {})
    target_ids = set(target_specs.keys())
    pools_with_draws = sum(1 for c in pool_draw_counts.values() if c > 0)
    if pools_with_draws == 0:
        return 0.0
    total_target_draws = sum(
        sum(cnt for cid, cnt in pool_cards.items() if cid in target_ids)
        for pool_cards in pool_card_counts.values()
    )
    return total_target_draws / pools_with_draws


def _gdr_weapon_character_ratio(compact, weapon_character_map=None, **kwargs):
    if not weapon_character_map:
        return 0.0
    card_counts = compact.get('card_counts', {})
    char_ids = set(weapon_character_map.values())
    char_count = sum(card_counts.get(cid, 0) for cid in char_ids)
    if char_count == 0:
        return 0.0
    weapon_count = 0
    for weapon_id, char_id in weapon_character_map.items():
        if card_counts.get(char_id, 0) > 0:
            weapon_count += card_counts.get(weapon_id, 0)
    return weapon_count / char_count


def _gdr_weighted_satisfaction(compact, target_specs, desire_weights=None, miss_cost_weights=None, **kwargs):
    card_counts = compact.get('card_counts', {})
    if not target_specs:
        return 0.0
    if desire_weights is None:
        desire_weights = {cid: 1.0 for cid in target_specs}
    if miss_cost_weights is None:
        miss_cost_weights = {cid: 1.0 for cid in target_specs}
    satisfaction = 0.0
    for card_id, qty in target_specs.items():
        got = min(card_counts.get(card_id, 0), qty)
        missed = max(qty - card_counts.get(card_id, 0), 0)
        satisfaction += got * desire_weights.get(card_id, 1.0)
        satisfaction -= missed * miss_cost_weights.get(card_id, 1.0)
    return satisfaction


def _gdr_total_card_value(compact, target_specs, card_value_weights=None, **kwargs):
    card_counts = compact.get('card_counts', {})
    if card_value_weights is None:
        card_value_weights = {cid: 1.0 for cid in target_specs}
    total_value = 0.0
    for card_id, cnt in card_counts.items():
        total_value += cnt * card_value_weights.get(card_id, 1.0)
    return total_value


def _gdr_target_card_draws(compact, target_specs, **kw):
    """不去重计数：所有目标卡的出现次数之和。用于 per_pool_target 判定。"""
    return sum(
        compact.get('card_counts', {}).get(cid, 0)
        for cid in target_specs
    )


def _gdr_resource_per_card(compact, target_specs, **kw):
    """每张目标卡的资源消耗。越低越好。"""
    resource_id = kw.get('resource_id', 'draw_resource')
    consumed = compact.get('total_consumed', {}).get(resource_id, 0)
    obtained = sum(
        min(compact.get('card_counts', {}).get(cid, 0), qty)
        for cid, qty in target_specs.items()
    )
    if obtained <= 0:
        return float('nan')
    return consumed / obtained


def _gdr_resource_consumed(compact, target_specs, **kw):
    """总资源消耗。越低越好。"""
    resource_id = kw.get('resource_id', 'draw_resource')
    return compact.get('total_consumed', {}).get(resource_id, 0)


def _gdr_draw_conversion_efficiency(compact, target_specs,
                                     cost_per_draw=160, **kw):
    """抽数转化效率 = 实际抽数 / (资源消耗 / 每抽成本)。越高越好。

    只计入类型为「角色」或「武器」的抽卡池的抽数，兑换池和资源池不计入。
    pool_type 为空时默认视为「角色」（计入）。
    """
    resource_consumed = compact.get('total_consumed', {}).get('draw_resource', 0)
    if resource_consumed <= 0 or cost_per_draw <= 0:
        return 0.0
    pool_types = compact.get('pool_types', {})
    pool_draw_counts = compact.get('pool_draw_counts', {})
    draw_pool_draws = 0
    for pid, cnt in pool_draw_counts.items():
        pt = pool_types.get(pid, '角色')
        if pt in ('角色', '武器', ''):
            draw_pool_draws += cnt
    if draw_pool_draws == 0:
        draw_pool_draws = compact.get('total_draws', 0)
    return (draw_pool_draws * cost_per_draw) / resource_consumed


class GDRDefinition(NamedTuple):
    key: str
    display_name: str
    default_threshold: float
    compute_from_compact: Callable[..., float]
    compute_from_history: Optional[Callable[..., float]] = None
    needs_ssr_ids: bool = False
    needs_weapon_map: bool = False
    needs_weights: str = ''
    category: str = 'basic'
    lower_is_better: bool = False
    compatible_with_min_resource: bool = True


UNIFIED_GDR_REGISTRY: Dict[str, GDRDefinition] = {
    'target_achievement': GDRDefinition(
        key='target_achievement',
        display_name='简单目标达成率',
        default_threshold=1.0,
        compute_from_compact=_gdr_target_achievement,
        compute_from_history=simple_target_achievement_rate,
    ),
    'target_collection': GDRDefinition(
        key='target_collection',
        display_name='目标卡收集率',
        default_threshold=1.0,
        compute_from_compact=_gdr_target_collection,
        compute_from_history=target_collection_rate,
    ),
    'all_targets': GDRDefinition(
        key='all_targets',
        display_name='抽出全部目标卡',
        default_threshold=1.0,
        compute_from_compact=_gdr_all_targets,
        compute_from_history=all_targets_obtained,
    ),
    'ssr_collection': GDRDefinition(
        key='ssr_collection',
        display_name='SSR收集率',
        default_threshold=0.05,
        compute_from_compact=_gdr_ssr_collection,
        compute_from_history=ssr_collection_rate,
        needs_ssr_ids=True,
    ),
    'resource_remaining': GDRDefinition(
        key='resource_remaining',
        display_name='资源剩余',
        default_threshold=0.0,
        compute_from_compact=_gdr_resource_remaining,
        compute_from_history=resource_remaining,
    ),
    'resource_consumed': GDRDefinition(
        key='resource_consumed',
        display_name='资源消耗',
        default_threshold=0.0,
        compute_from_compact=_gdr_resource_consumed,
        lower_is_better=True,
        compatible_with_min_resource=False,
        category='resource',
    ),
    'extra_target': GDRDefinition(
        key='extra_target',
        display_name='额外目标卡',
        default_threshold=0.0,
        compute_from_compact=_gdr_extra_target,
        compute_from_history=extra_target_cards,
    ),
    'non_pity_draws': GDRDefinition(
        key='non_pity_draws',
        display_name='非保底抽卡数',
        default_threshold=0.0,
        compute_from_compact=_gdr_non_pity_draws,
        compute_from_history=non_pity_draws,
    ),
    'pity_draws': GDRDefinition(
        key='pity_draws',
        display_name='保底抽卡数',
        default_threshold=0.0,
        compute_from_compact=_gdr_pity_draws,
        compute_from_history=pity_draws,
    ),
    'resource_efficiency': GDRDefinition(
        key='resource_efficiency',
        display_name='目标卡出卡效率',
        default_threshold=0.01,
        compute_from_compact=_gdr_resource_efficiency,
        compute_from_history=resource_efficiency,
        compatible_with_min_resource=False,
    ),
    'resource_per_card': GDRDefinition(
        key='resource_per_card',
        display_name='每目标卡资源消耗',
        default_threshold=0.0,
        compute_from_compact=_gdr_resource_per_card,
        lower_is_better=True,
        compatible_with_min_resource=False,
        category='resource',
    ),
    'per_pool_draw_rate': GDRDefinition(
        key='per_pool_draw_rate',
        display_name='每池下池出卡率',
        default_threshold=0.0,
        compute_from_compact=_gdr_per_pool_draw_rate,
        compute_from_history=per_pool_draw_rate,
    ),
    'weapon_character_ratio': GDRDefinition(
        key='weapon_character_ratio',
        display_name='专武角色比',
        default_threshold=0.0,
        compute_from_compact=_gdr_weapon_character_ratio,
        compute_from_history=weapon_character_ratio,
        needs_weapon_map=True,
    ),
    'target_card_draws': GDRDefinition(
        key='target_card_draws',
        display_name='目标卡出数',
        default_threshold=1.0,
        compute_from_compact=_gdr_target_card_draws,
    ),
    'weighted_satisfaction': GDRDefinition(
        key='weighted_satisfaction',
        display_name='加权满意度',
        default_threshold=0.0,
        compute_from_compact=_gdr_weighted_satisfaction,
        compute_from_history=None,
        needs_weights='desire+miss_cost',
        category='weighted',
    ),
    'total_card_value': GDRDefinition(
        key='total_card_value',
        display_name='总出卡价值',
        default_threshold=0.0,
        compute_from_compact=_gdr_total_card_value,
        compute_from_history=None,
        needs_weights='card_value',
        category='weighted',
    ),
    'draw_conversion_efficiency': GDRDefinition(
        key='draw_conversion_efficiency',
        display_name='抽数转化效率',
        default_threshold=0.0,
        compute_from_compact=_gdr_draw_conversion_efficiency,
        compatible_with_min_resource=False,
        category='resource',
    ),
}


# ============================================================
# 多资源类型支持 —— 公共辅助函数
# ============================================================

# 需要按资源类型展开的 GDR key 集合（模块内部常量）
_RESOURCE_GDR_KEYS: set = {'resource_remaining', 'resource_consumed',
                            'resource_per_card', 'resource_efficiency'}


def parse_gdr_key(gdr_key: str) -> tuple:
    """解析 GDR key，返回 (base_key, resource_id)。

    :qualified key 以 ``:`` 分隔 base_key 和 resource_id。
    不含 ``:`` 时默认 resource_id='draw_resource'。

    >>> parse_gdr_key('resource_remaining')
    ('resource_remaining', 'draw_resource')
    >>> parse_gdr_key('resource_remaining:exchange_currency')
    ('resource_remaining', 'exchange_currency')
    >>> parse_gdr_key('target_achievement')
    ('target_achievement', 'draw_resource')
    """
    if gdr_key is None:
        return '', 'draw_resource'
    if ':' in gdr_key:
        base_key, resource_id = gdr_key.split(':', 1)
        return base_key, resource_id
    return gdr_key, 'draw_resource'


def is_resource_gdr(gdr_key: str) -> bool:
    """判断 gdr_key（含 :qualified 格式）是否属于资源类 GDR。

    >>> is_resource_gdr('resource_remaining')
    True
    >>> is_resource_gdr('resource_remaining:exchange_currency')
    True
    >>> is_resource_gdr('target_achievement')
    False
    """
    base_key, _ = parse_gdr_key(gdr_key)
    return base_key in _RESOURCE_GDR_KEYS


def resolve_gdr_definition(gdr_key: str) -> Optional[GDRDefinition]:
    """两步查找 GDR 定义：先试完整 key，回退解析 base_key。

    用于所有需要从 gdr_key 获取 GDRDefinition 元数据的消费方。
    与 compute_gdr_from_compact() 的区别：此函数仅返回定义，不执行计算。
    """
    defn = UNIFIED_GDR_REGISTRY.get(gdr_key)
    if defn is not None:
        return defn
    base_key, _ = parse_gdr_key(gdr_key)
    return UNIFIED_GDR_REGISTRY.get(base_key)


def get_expanded_gdr_entries(resource_defs=None):
    """返回展开后的 GDR 条目列表 [(key, display_name, lower_is_better, default_threshold)]。

    纯函数，不修改全局状态。
    - resource_defs 为 None → 17 条，等价遍历原始注册表
    - resource_defs 不为 None → 资源类 GDR 按资源类型展开为 :qualified 条目

    >>> entries = get_expanded_gdr_entries()
    >>> len(entries)
    17
    >>> entries = get_expanded_gdr_entries({'draw_resource': '抽卡资源', 'exchange_currency': '兑换货币'})
    >>> len(entries)
    21
    """
    entries = []
    for key, defn in UNIFIED_GDR_REGISTRY.items():
        if key in _RESOURCE_GDR_KEYS and resource_defs:
            for rid, rname in resource_defs.items():
                entries.append((
                    f'{key}:{rid}',
                    f'{defn.display_name} ({rname})',
                    defn.lower_is_better,
                    defn.default_threshold,
                ))
        else:
            entries.append((
                key, defn.display_name,
                defn.lower_is_better, defn.default_threshold,
            ))
    return entries


def register_gdr(definition: GDRDefinition, *, overwrite: bool = False) -> None:
    existing = UNIFIED_GDR_REGISTRY.get(definition.key)
    if existing is not None and not overwrite:
        if existing.display_name != definition.display_name:
            raise ValueError(
                f"GDR key '{definition.key}' already registered as "
                f"'{existing.display_name}', cannot re-register as "
                f"'{definition.display_name}'. Use overwrite=True to force."
            )
        return
    for k, v in UNIFIED_GDR_REGISTRY.items():
        if k != definition.key and v.display_name == definition.display_name:
            raise ValueError(
                f"GDR display_name '{definition.display_name}' already used "
                f"by key '{k}'. Choose a different display_name."
            )
    UNIFIED_GDR_REGISTRY[definition.key] = definition


def _build_legacy_registries():
    gdr_registry = {}
    compact_gdr_registry = {}
    for key, defn in UNIFIED_GDR_REGISTRY.items():
        compact_gdr_registry[key] = (defn.display_name, defn.default_threshold)
        if defn.compute_from_history is not None:
            gdr_registry[defn.display_name] = defn.compute_from_history
    return gdr_registry, compact_gdr_registry


GDR_REGISTRY, COMPACT_GDR_REGISTRY = _build_legacy_registries()


def compute_all_gdr(history, ctx: GDRContext) -> Dict[str, float]:
    return {name: func(history, ctx) for name, func in GDR_REGISTRY.items()}


def compute_collection_rates(history, ctx: GDRContext) -> Dict[str, float]:
    rates = {}
    for name, card_set in ctx.collection_sets.items():
        rates[f'{name}收集率'] = card_collection_rate(history, ctx, name, card_set)
    return rates


def compute_weighted_gdr(
    history, ctx: GDRContext,
    weight_config_or_func: Any,
    miss_cost_func: Callable[[str], float] = None
) -> Dict[str, float]:
    if callable(weight_config_or_func):
        get_weight = weight_config_or_func
    else:
        get_weight = weight_config_or_func.create_weight_function('default')

    results = {
        '加权目标达成率': weighted_target_achievement_rate(history, ctx, get_weight),
        '加权额外卡': weighted_extra_cards(history, ctx, get_weight),
        '遗憾指数': regret_index(history, ctx, get_weight),
        '总出卡价值': total_card_value(history, ctx, get_weight),
    }
    if miss_cost_func is not None:
        results['加权满意度'] = weighted_satisfaction(history, ctx, get_weight, miss_cost_func)
    return results


def compute_custom_weighted_gdr(
    history, ctx: GDRContext,
    gdr_weight_configs: Dict[str, Any],
    miss_cost_func: Callable[[str], float] = None
) -> Dict[str, float]:
    results = {}

    for gdr_name, config in gdr_weight_configs.items():
        if gdr_name == '加权目标达成率':
            get_weight = config if callable(config) else config.create_weight_function(
                config.scheme_map.get('加权目标达成率', 'default')
            )
            results[gdr_name] = weighted_target_achievement_rate(history, ctx, get_weight)

        elif gdr_name == '加权额外卡':
            get_weight = config if callable(config) else config.create_weight_function(
                config.scheme_map.get('加权额外卡', 'default')
            )
            results[gdr_name] = weighted_extra_cards(history, ctx, get_weight)

        elif gdr_name == '遗憾指数':
            get_weight = config if callable(config) else config.create_weight_function(
                config.scheme_map.get('遗憾指数', 'default')
            )
            results[gdr_name] = regret_index(history, ctx, get_weight)

        elif gdr_name == '总出卡价值':
            get_weight = config if callable(config) else config.create_weight_function(
                config.scheme_map.get('总出卡价值', 'default')
            )
            results[gdr_name] = total_card_value(history, ctx, get_weight)

        elif gdr_name == '加权满意度':
            get_weight = config if callable(config) else config.create_weight_function(
                config.scheme_map.get('加权满意度', 'default')
            )
            if miss_cost_func is not None:
                results[gdr_name] = weighted_satisfaction(history, ctx, get_weight, miss_cost_func)

    return results


def compute_gdr_from_compact(
    compact: Union[Dict[str, Any], CompactResult],
    target_specs: Dict[str, int],
    gdr_key: str = 'target_achievement',
    desire_weights: Dict[str, float] = None,
    miss_cost_weights: Dict[str, float] = None,
    card_value_weights: Dict[str, float] = None,
    ssr_ids: Set[str] = None,
    weapon_character_map: Dict[str, str] = None,
    **gdr_kwargs,
) -> float:
    _, resource_id = parse_gdr_key(gdr_key)
    defn = resolve_gdr_definition(gdr_key)
    if defn is None:
        return 0.0
    gdr_kwargs.pop('resource_id', None)  # 防冲突：解析值优先
    return defn.compute_from_compact(
        compact,
        target_specs=target_specs,
        desire_weights=desire_weights,
        miss_cost_weights=miss_cost_weights,
        card_value_weights=card_value_weights,
        ssr_ids=ssr_ids,
        weapon_character_map=weapon_character_map,
        resource_id=resource_id,
        **gdr_kwargs,
    )


class GDRCalculator:
    """绑定了 gdr_key + 权重的 GDR 计算器。

    构造后零参调用 compute_gdr() / is_success() / check_batch()。
    推荐通过 make_gdr_calculator() 工厂函数构造——自动从 ConfigStore 提取权重。
    """
    def __init__(self, target_specs, gdr_key='target_achievement',
                 gdr_threshold=None,
                 desire_weights=None, miss_cost_weights=None,
                 card_value_weights=None, ssr_ids=None,
                 weapon_character_map=None):
        self.target_specs = target_specs
        self.gdr_key = gdr_key
        self.desire_weights = desire_weights
        self.miss_cost_weights = miss_cost_weights
        self.card_value_weights = card_value_weights
        self.ssr_ids = ssr_ids
        self.weapon_character_map = weapon_character_map

        defn = resolve_gdr_definition(gdr_key)
        if gdr_threshold is None:
            self.gdr_threshold = defn.default_threshold if defn else 1.0
        else:
            self.gdr_threshold = gdr_threshold
        self.lower_is_better = defn.lower_is_better if defn else False

    def compute_gdr(self, compact_or_aggregate):
        return compute_gdr_from_compact(
            compact_or_aggregate,
            target_specs=self.target_specs,
            gdr_key=self.gdr_key,
            desire_weights=self.desire_weights,
            miss_cost_weights=self.miss_cost_weights,
            card_value_weights=self.card_value_weights,
            ssr_ids=self.ssr_ids,
            weapon_character_map=self.weapon_character_map,
        )

    def is_success(self, compact_or_aggregate):
        val = self.compute_gdr(compact_or_aggregate)
        if self.lower_is_better:
            return val <= self.gdr_threshold
        return val >= self.gdr_threshold

    def check_batch(self, results):
        total = 0
        success = 0
        for r in results:
            if r is not None:
                total += 1
                if self.is_success(r):
                    success += 1
        prob = success / total if total > 0 else 0.0
        return success, total, prob


def make_gdr_calculator(store, target_specs, gdr_key, *,
                         gdr_threshold=None, ssr_ids=None,
                         weapon_character_map=None) -> GDRCalculator:
    """从 ConfigStore 提取权重，构造 GDRCalculator。

    调用方只需传 store + target_specs + gdr_key。
    权重从 ConfigStore.xxx_weights 自动提取，不可能遗漏。
    """
    return GDRCalculator(
        target_specs=target_specs,
        gdr_key=gdr_key,
        gdr_threshold=gdr_threshold,
        desire_weights=store.desire_weights,
        miss_cost_weights=store.miss_cost_weights,
        card_value_weights=store.card_value_weights,
        ssr_ids=ssr_ids,
        weapon_character_map=weapon_character_map,
    )


def compute_success_probability(
    histories,
    target_specs: Dict[str, int],
    gdr_key: str = 'target_achievement',
    gdr_threshold: float = 1.0,
    desire_weights: Dict[str, float] = None,
    miss_cost_weights: Dict[str, float] = None,
    card_value_weights: Dict[str, float] = None,
    ssr_ids: Set[str] = None,
    weapon_character_map: Dict[str, str] = None,
) -> float:
    valid = [h for h in histories if h is not None]
    if not valid:
        return 0.0
    total_needed = sum(target_specs.values())
    if total_needed == 0 and gdr_key == 'target_achievement':
        return 1.0
    defn = resolve_gdr_definition(gdr_key)
    lower_is_better = defn.lower_is_better if defn else False
    success_count = 0
    for h in valid:
        val = compute_gdr_from_compact(
            h, target_specs, gdr_key,
            desire_weights, miss_cost_weights, card_value_weights,
            ssr_ids, weapon_character_map,
        )
        if lower_is_better:
            if val <= gdr_threshold:
                success_count += 1
        else:
            if val >= gdr_threshold:
                success_count += 1
    return success_count / len(valid)


def populate_gdr_combo(combo, resource_defs=None):
    combo.clear()
    entries = get_expanded_gdr_entries(resource_defs)
    for key, display_name, lower_is_better, _default_threshold in entries:
        display = ('(-)' + display_name) if lower_is_better else display_name
        combo.addItem(display, key)


def get_default_threshold(gdr_key: str) -> float:
    if gdr_key is None:
        return 1.0
    defn = resolve_gdr_definition(gdr_key)
    return defn.default_threshold if defn else 1.0


def compute_gdr_from_cumulative(cum_snapshot, target_specs, gdr_key,
                                 desire_weights=None, miss_cost_weights=None,
                                 card_value_weights=None, ssr_ids=None,
                                 weapon_character_map=None,
                                 initial_resources=None,
                                 **gdr_kwargs):
    cum_consumed = cum_snapshot.get('cumulative_consumed', {})
    cum_gained = cum_snapshot.get('cumulative_gained', {})
    _, resource_id = parse_gdr_key(gdr_key)
    # 优先使用多资源 dict（P22 扩展），回退旧格式标量 pool_end_resource
    pool_end_resources = cum_snapshot.get('pool_end_resources')
    if pool_end_resources is not None:
        pseudo_final_resources = dict(pool_end_resources)
    else:
        pool_end_resource = cum_snapshot.get('pool_end_resource')
        if pool_end_resource is not None:
            pseudo_final_resources = {resource_id: pool_end_resource}
        else:
            pseudo_final_resources = {}
            if initial_resources:
                for k, v in initial_resources.items():
                    pseudo_final_resources[k] = v
            for k in set(list(cum_consumed.keys()) + list(cum_gained.keys())):
                pseudo_final_resources[k] = pseudo_final_resources.get(k, 0) + cum_gained.get(k, 0) - cum_consumed.get(k, 0)

    pseudo_compact = {
        'card_counts': cum_snapshot.get('cumulative_card_counts', {}),
        'total_draws': cum_snapshot.get('cumulative_draws', 0),
        'pity_triggers': cum_snapshot.get('cumulative_pity_draws', 0),
        'total_consumed': cum_consumed,
        'total_gained': cum_gained,
        'final_resources': pseudo_final_resources,
        'pool_draw_counts': {},
        'pool_card_counts': {},
        'pool_pity_counts': {},
    }
    return compute_gdr_from_compact(
        pseudo_compact, target_specs, gdr_key,
        desire_weights, miss_cost_weights, card_value_weights,
        ssr_ids, weapon_character_map,
        **gdr_kwargs,
    )
