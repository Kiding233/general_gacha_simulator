import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional

from .pool import Pool, Reward, parse_cost_string, PoolCost
from .schedule import PoolSchedule, PoolScheduleManager
from .target_card import TargetCard, TargetCardSet
from .pity import build_pity_engine


@dataclass
class CardDef:
    card_id: str
    rarity: str
    name: str
    pools: List[str] = field(default_factory=list)
    rerun_of: Optional[str] = None
    initial_count: int = 0


@dataclass
class CardCatalog:
    cards: Dict[str, CardDef] = field(default_factory=dict)

    def add_card(self, card_id: str, rarity: str, name: str = None, pools: List[str] = None, initial_count: int = 0):
        self.cards[card_id] = CardDef(
            card_id=card_id,
            rarity=rarity,
            name=name or card_id,
            pools=pools or [],
            initial_count=initial_count,
        )

    def get_card(self, card_id: str) -> Optional[CardDef]:
        return self.cards.get(card_id)

    def get_rerun_cards(self) -> List[CardDef]:
        return [c for c in self.cards.values() if c.rerun_of is not None]

    def get_rerun_of(self, pool_id: str) -> List[CardDef]:
        return [c for c in self.cards.values() if c.rerun_of == pool_id]

    def merge(self, other: 'CardCatalog'):
        for card_id, card_def in other.cards.items():
            if card_id in self.cards:
                existing = self.cards[card_id]
                if not existing.name or existing.name == existing.card_id:
                    existing.name = card_def.name
                if not existing.rarity or existing.rarity == existing.card_id:
                    existing.rarity = card_def.rarity
                if card_def.initial_count > 0:
                    existing.initial_count = max(existing.initial_count, card_def.initial_count)
                for pid in card_def.pools:
                    if pid not in existing.pools:
                        existing.pools.append(pid)
            else:
                self.cards[card_id] = CardDef(
                    card_id=card_def.card_id,
                    rarity=card_def.rarity,
                    name=card_def.name,
                    pools=list(card_def.pools),
                    rerun_of=card_def.rerun_of,
                    initial_count=card_def.initial_count,
                )


def parse_cards_file(filepath: str) -> CardCatalog:
    catalog = CardCatalog()
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('|')
                if len(parts) < 3:
                    continue
                card_id = parts[0].strip()
                name = parts[1].strip()
                rarity = parts[2].strip()
                initial_count = 0
                if len(parts) >= 4:
                    try:
                        initial_count = int(parts[3].strip())
                    except ValueError:
                        pass
                catalog.add_card(card_id, rarity, name, initial_count=initial_count)
    except FileNotFoundError:
        pass
    return catalog


@dataclass
class PoolConfig:
    pool_id: str
    name: str
    start_day: float
    end_day: float
    cost_str: str
    distribution_file: str
    bindings: Dict[str, str] = field(default_factory=dict)
    target_specs: List[Tuple[str, int]] = field(default_factory=list)
    rerun_of: Optional[str] = None
    exchange_card_id: Optional[str] = None

    @property
    def cost(self) -> PoolCost:
        return parse_cost_string(self.cost_str)


def parse_schedule_file(filepath: str) -> Tuple[List[PoolConfig], CardCatalog]:
    configs = []
    catalog = CardCatalog()

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('|')
            if len(parts) < 6:
                continue
            pool_id = parts[0].strip()
            name = parts[1].strip()
            start_day = float(parts[2].strip())
            end_day = float(parts[3].strip())
            cost_str = parts[4].strip()
            dist_file = parts[5].strip() if len(parts) > 5 else f"{pool_id}.txt"
            bindings = {}
            rerun_of = None
            exchange_card_id = None
            if len(parts) > 6 and parts[6].strip():
                for pair in parts[6].strip().split(';'):
                    kv = pair.strip().split('=', 1)
                    if len(kv) == 2:
                        k = kv[0].strip()
                        v = kv[1].strip()
                        if k == 'rerun_of':
                            rerun_of = v
                        elif k == 'exchange_card':
                            exchange_card_id = v
                        else:
                            bindings[k] = v
            target_specs = []
            if len(parts) > 7 and parts[7].strip():
                for t in parts[7].split(','):
                    t = t.strip()
                    if ':' in t:
                        cid, qty = t.rsplit(':', 1)
                        try:
                            target_specs.append((cid.strip(), int(qty.strip())))
                        except ValueError:
                            target_specs.append((t, 1))
                    else:
                        target_specs.append((t, 1))

            pc = PoolConfig(
                pool_id=pool_id, name=name,
                start_day=start_day, end_day=end_day,
                cost_str=cost_str,
                distribution_file=dist_file, bindings=bindings,
                target_specs=target_specs,
                rerun_of=rerun_of,
                exchange_card_id=exchange_card_id,
            )
            configs.append(pc)

            RARITY_BINDING_KEYS = {'ssr': 'ssr', 'ssr_alt': 'ssr', 'ssr_alt1': 'ssr', 'ssr_alt2': 'ssr', 'featured': 'ssr', 'offrate': 'ssr', 'sr': 'sr', 'r': 'r'}
            for key, val in bindings.items():
                rarity = RARITY_BINDING_KEYS.get(key)
                if rarity is None:
                    continue
                for cid in val.split(','):
                    cid = cid.split(':')[0].strip()
                    existing = catalog.get_card(cid)
                    if existing:
                        if pool_id not in existing.pools:
                            existing.pools.append(pool_id)
                    else:
                        catalog.add_card(cid, rarity, pools=[pool_id])

            for tid, qty in target_specs:
                if tid not in [c.card_id for c in catalog.cards.values()]:
                    catalog.add_card(tid, 'ssr', pools=[pool_id])

    return configs, catalog


def parse_distribution_file(filepath: str, bindings: Dict[str, str] = None) -> List[Tuple[Reward, float]]:
    if bindings is None:
        bindings = {}

    raw_lines = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            raw_lines.append(line)

    nesting_defs: Dict[str, List[str]] = {}
    prob_defs: Dict[str, float] = {}
    card_id_defs: Dict[str, str] = {}

    for line in raw_lines:
        bracket_eq_list = re.match(r'^\[(\w+)\]\s*=\s*\[(.+)\]$', line)
        if bracket_eq_list:
            key = bracket_eq_list.group(1)
            sub_keys = [s.strip() for s in bracket_eq_list.group(2).split(',')]
            nesting_defs[key] = sub_keys
            continue

        prob_match = re.match(r'^\[(\w+)\]\s*:\s*([\d.]+)$', line)
        if prob_match:
            key = prob_match.group(1)
            prob = float(prob_match.group(2))
            prob_defs[key] = prob
            continue

        id_match = re.match(r'^\[(\w+)\]\s*=\s*(.+)$', line)
        if id_match:
            key = id_match.group(1)
            card_id_defs[key] = id_match.group(2).strip()
            continue

    def is_nested_child(key: str) -> bool:
        for children in nesting_defs.values():
            if key in children:
                return True
        return False

    top_keys = []
    for line in raw_lines:
        m = re.match(r'^\[(\w+)\]\s*[=:]', line)
        if not m:
            continue
        key = m.group(1)
        if not is_nested_child(key) and key not in top_keys:
            top_keys.append(key)

    def resolve_leaves(key: str, abs_prob: float) -> List[Tuple[str, float]]:
        if key not in nesting_defs:
            return [(key, abs_prob)]
        children = nesting_defs[key]
        child_probs = {c: prob_defs.get(c, 0.0) for c in children}
        rel_sum = sum(child_probs.values())
        if rel_sum <= 0:
            share = abs_prob / len(children)
            return [(c, share) for c in children]
        results = []
        for c in children:
            c_abs = abs_prob * (child_probs[c] / rel_sum)
            results.extend(resolve_leaves(c, c_abs))
        return results

    all_leaves: List[Tuple[str, float]] = []
    for key in top_keys:
        abs_prob = prob_defs.get(key, 0.0)
        all_leaves.extend(resolve_leaves(key, abs_prob))

    rewards: List[Tuple[Reward, float]] = []
    for leaf_key, prob in all_leaves:
        cid = card_id_defs.get(leaf_key, leaf_key)
        resolved = bindings.get(cid, cid)
        if resolved.startswith('$'):
            resolved = bindings.get(resolved[1:], resolved)
        expanded = _expand_binding(resolved, prob)
        for card_id, card_prob in expanded:
            reward = Reward(id=card_id, name=card_id, resources_gained={}, extra_info={})
            rewards.append((reward, card_prob))

    return rewards


def _expand_binding(value: str, prob: float) -> List[Tuple[str, float]]:
    if ',' not in value:
        return [(value, prob)]
    parts = [p.strip() for p in value.split(',')]
    weighted = []
    unweighted = []
    for part in parts:
        if ':' in part:
            cid, w = part.rsplit(':', 1)
            try:
                weight = float(w)
                weighted.append((cid.strip(), weight))
            except ValueError:
                weighted.append((part.strip(), 1.0))
        else:
            unweighted.append(part.strip())
    if not weighted and not unweighted:
        return [(value, prob)]
    total_weight = sum(w for _, w in weighted) + len(unweighted)
    results = []
    for cid, w in weighted:
        results.append((cid, prob * (w / total_weight)))
    for cid in unweighted:
        results.append((cid, prob * (1.0 / total_weight)))
    return results


def load_config_from_directory(config_dir: str, schedule_file: str = 'schedule.txt', cards_file: str = 'cards.txt'):
    schedule_path = os.path.join(config_dir, schedule_file)
    pool_configs, schedule_catalog = parse_schedule_file(schedule_path)

    cards_path = os.path.join(config_dir, cards_file)
    file_catalog = parse_cards_file(cards_path)

    card_catalog = file_catalog
    card_catalog.merge(schedule_catalog)

    pools = []
    targets = []
    schedules = []
    all_target_ids = []
    featured_ids_map: Dict[str, Set[str]] = {}
    ssr_ids_map: Dict[str, Set[str]] = {}

    DAY = 86400

    SSR_BINDING_KEYS = {'ssr', 'ssr_alt', 'ssr_alt1', 'ssr_alt2', 'featured', 'offrate'}

    for pc in pool_configs:
        if os.path.isabs(pc.distribution_file):
            dist_path = pc.distribution_file
        else:
            dist_path = os.path.join(config_dir, pc.distribution_file)

        if pc.exchange_card_id:
            card_name = pc.exchange_card_id
            card_def = card_catalog.get_card(pc.exchange_card_id)
            if card_def:
                card_name = card_def.name
            reward = Reward(
                id=pc.exchange_card_id,
                name=card_name,
                resources_gained={},
                extra_info={'is_exchange': True}
            )
            rewards = [(reward, 1.0)]
        else:
            rewards = parse_distribution_file(dist_path, pc.bindings)

        pool = Pool(
            id=pc.pool_id, name=pc.name,
            cost=pc.cost,
            rewards=rewards,
            available_from=pc.start_day * DAY,
            available_until=pc.end_day * DAY,
            is_rerun=pc.rerun_of is not None,
            original_pool_id=pc.rerun_of,
            is_exchange=pc.exchange_card_id is not None,
            exchange_card_id=pc.exchange_card_id,
        )
        pools.append(pool)

        schedules.append(PoolSchedule(
            pool_id=pc.pool_id,
            available_from=pc.start_day * DAY,
            available_until=pc.end_day * DAY,
            rerun_of=pc.rerun_of,
        ))

        featured: Set[str] = set()
        ssr_all: Set[str] = set()
        for key, val in pc.bindings.items():
            if key in SSR_BINDING_KEYS:
                for cid in val.split(','):
                    cid = cid.split(':')[0].strip()
                    ssr_all.add(cid)
                    if key in ('ssr', 'featured'):
                        featured.add(cid)
        for tid, qty in pc.target_specs:
            featured.add(tid)
            ssr_all.add(tid)
        featured_ids_map[pc.pool_id] = featured
        ssr_ids_map[pc.pool_id] = ssr_all

        card_pools = [pc.pool_id]
        if pc.rerun_of:
            card_pools.append(pc.rerun_of)

        for tid, qty in pc.target_specs:
            if tid not in all_target_ids:
                all_target_ids.append(tid)

            card_def = card_catalog.get_card(tid)
            if card_def and pc.pool_id not in card_def.pools:
                card_def.pools.append(pc.pool_id)

            targets.append(TargetCard(
                card_id=tid, pool_ids=card_pools, quantity_needed=qty,
            ))

    all_ssr_ids: Set[str] = set()
    all_drawable_ids: Set[str] = set()
    for pc in pool_configs:
        for key, val in pc.bindings.items():
            if key in SSR_BINDING_KEYS:
                for cid in val.split(','):
                    cid = cid.split(':')[0].strip()
                    all_ssr_ids.add(cid)
        if os.path.isabs(pc.distribution_file):
            dist_path = pc.distribution_file
        else:
            dist_path = os.path.join(config_dir, pc.distribution_file)
        rewards = parse_distribution_file(dist_path, pc.bindings)
        for reward, _ in rewards:
            all_drawable_ids.add(reward.id)

    target_set = TargetCardSet(targets)
    schedule_mgr = PoolScheduleManager(schedules)

    pool_ids = [pc.pool_id for pc in pool_configs]
    pity_engine = build_pity_engine(config_dir, pool_ids, featured_ids_map, ssr_ids_map)

    return pools, target_set, schedule_mgr, all_target_ids, pity_engine, all_ssr_ids, sorted(all_drawable_ids), card_catalog
