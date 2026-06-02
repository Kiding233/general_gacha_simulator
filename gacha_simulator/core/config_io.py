import os
from typing import Dict, List, Optional

from .config_store import (
    ConfigStore, CardDefEntry, PoolEntry, PoolDistEntry,
    PityConfig, PityDef,
    GainRule, DayOverride, TargetCardEntry,
    CardWeightEntry,
)
from .pool_config import parse_schedule_file, parse_cards_file, parse_distribution_file
from .pity import parse_pity_file
from .resource_gain import parse_gains_file, parse_resources_file


def load_store_from_directory(dir_path: str, store: Optional[ConfigStore] = None) -> ConfigStore:
    if store is None:
        store = ConfigStore()
    else:
        store.clear()

    _load_resources(dir_path, store)
    _load_cards(dir_path, store)
    _load_schedule(dir_path, store)
    _load_pity(dir_path, store)
    _load_gains(dir_path, store)
    _load_initial_resources(dir_path, store)
    _load_targets(dir_path, store)
    _load_weights(dir_path, store)

    return store


def save_store_to_directory(dir_path: str, store: ConfigStore):
    os.makedirs(dir_path, exist_ok=True)
    os.makedirs(os.path.join(dir_path, 'pools'), exist_ok=True)

    _save_resources(dir_path, store)
    _save_cards(dir_path, store)
    _save_schedule(dir_path, store)
    _save_pity(dir_path, store)
    _save_gains(dir_path, store)
    _save_initial_resources(dir_path, store)
    _save_targets(dir_path, store)
    _save_weights(dir_path, store)
    _save_distributions(dir_path, store)


def _load_resources(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'resources.txt')
    store.resource_defs = parse_resources_file(filepath)


def _load_cards(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'cards.txt')
    catalog = parse_cards_file(filepath)
    store.card_defs = []
    for card_id, card_def in catalog.cards.items():
        store.card_defs.append(CardDefEntry(
            card_id=card_def.card_id,
            name=card_def.name,
            rarity=card_def.rarity,
            pools=list(card_def.pools),
            initial_count=getattr(card_def, 'initial_count', 0),
        ))


def _load_schedule(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'schedule.txt')
    if not os.path.exists(filepath):
        return

    pool_configs, schedule_catalog = parse_schedule_file(filepath)

    for card_id, card_def in schedule_catalog.cards.items():
        existing = next((c for c in store.card_defs if c.card_id == card_id), None)
        if existing:
            for pid in card_def.pools:
                if pid not in existing.pools:
                    existing.pools.append(pid)
            if not existing.name or existing.name == existing.card_id:
                existing.name = card_def.name
            ic = getattr(card_def, 'initial_count', 0)
            if ic > 0:
                existing.initial_count = max(existing.initial_count, ic)
        else:
            store.card_defs.append(CardDefEntry(
                card_id=card_def.card_id,
                name=card_def.name,
                rarity=card_def.rarity,
                pools=list(card_def.pools),
                initial_count=getattr(card_def, 'initial_count', 0),
            ))

    store.pools = []
    for pc in pool_configs:
        dist_file = pc.distribution_file
        if not os.path.isabs(dist_file):
            dist_path = os.path.join(dir_path, dist_file)
        else:
            dist_path = dist_file

        distribution = []
        if pc.exchange_card_id:
            distribution = [PoolDistEntry(
                card_id=pc.exchange_card_id,
                probability=100.0,
                rarity='ssr',
                featured=True,
            )]
        elif os.path.exists(dist_path):
            ssr_ids = _get_ssr_ids_from_bindings(pc.bindings)
            sr_ids = _get_sr_ids_from_bindings(pc.bindings)
            featured_ids = _get_featured_ids_from_bindings(pc.bindings)
            rewards = parse_distribution_file(dist_path, pc.bindings)
            for reward, prob in rewards:
                rg = reward.resources_gained if hasattr(reward, 'resources_gained') else {}
                if reward.id in ssr_ids:
                    rarity = 'ssr'
                elif reward.id in sr_ids:
                    rarity = 'sr'
                else:
                    rarity = 'r'
                distribution.append(PoolDistEntry(
                    card_id=reward.id,
                    probability=prob * 100.0,
                    rarity=rarity,
                    featured=reward.id in featured_ids,
                    resources_gained=rg if isinstance(rg, dict) else {},
                    first_time_bonus=dict(getattr(reward, 'first_time_bonus', {}) or {}),
                    nth_time_bonus=dict(getattr(reward, 'nth_time_bonus', {}) or {}),
                    excess_bonus=dict(getattr(reward, 'excess_bonus', {}) or {}),
                ))

        pool_entry = PoolEntry(
            enabled=True,
            pool_id=pc.pool_id,
            name=pc.name,
            start_day=int(pc.start_day),
            end_day=int(pc.end_day),
            cost=pc.cost_str,
            distribution_file=dist_file,
            bindings=dict(pc.bindings),
            target_specs=list(pc.target_specs),
            rerun_of=pc.rerun_of,
            exchange_card_id=pc.exchange_card_id,
            distribution=distribution,
        )
        store.pools.append(pool_entry)


def _get_ssr_ids_from_bindings(bindings: Dict[str, str]) -> set:
    ssr_keys = {'ssr', 'ssr_alt', 'ssr_alt1', 'ssr_alt2', 'featured', 'offrate'}
    ids = set()
    for key, val in bindings.items():
        if key in ssr_keys:
            for cid in val.split(','):
                ids.add(cid.split(':')[0].strip())
    return ids


def _get_sr_ids_from_bindings(bindings: Dict[str, str]) -> set:
    ids = set()
    val = bindings.get('sr', '')
    if val:
        for cid in val.split(','):
            ids.add(cid.split(':')[0].strip())
    return ids


def _get_r_ids_from_bindings(bindings: Dict[str, str]) -> set:
    ids = set()
    val = bindings.get('r', '')
    if val:
        for cid in val.split(','):
            ids.add(cid.split(':')[0].strip())
    return ids


def _get_featured_ids_from_bindings(bindings: Dict[str, str]) -> set:
    ids = set()
    for key in ('ssr', 'featured'):
        val = bindings.get(key, '')
        if val:
            for cid in val.split(','):
                ids.add(cid.split(':')[0].strip())
    return ids


def _load_pity(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'pity.txt')
    if not os.path.exists(filepath):
        store.pity = PityConfig(enabled=True)
        return

    parsed_defs = parse_pity_file(filepath)

    pities = []
    for pdef in parsed_defs:
        pities.append(PityDef(
            name=pdef.name,
            btype=pdef.btype,
            params=dict(pdef.params),
            target_distribution=dict(pdef.target_distribution),
            reset_condition=pdef.reset_condition,
            pools=pdef.pools,
        ))

    store.pity = PityConfig(enabled=True, pities=pities)


def _load_gains(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'gains.txt')
    if not os.path.exists(filepath):
        return

    rules: List[GainRule] = []
    day_overrides: List[DayOverride] = []

    current_rule = None
    current_gains: Dict[str, float] = {}

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if line.startswith('[') and line.endswith(']'):
                if current_rule is not None and current_gains:
                    rules.append(GainRule(rule_type=current_rule, gains=current_gains.copy()))
                current_rule = line[1:-1].strip()
                current_gains = {}
                continue

            if line.startswith('day:'):
                if current_rule is not None and current_gains:
                    rules.append(GainRule(rule_type=current_rule, gains=current_gains.copy()))
                    current_rule = None
                    current_gains = {}

                rest = line[4:].strip()
                parts = rest.split('|', 1)
                if len(parts) == 2:
                    day_num = int(parts[0].strip())
                    gains = _parse_resource_amount(parts[1].strip())
                    day_overrides.append(DayOverride(day=day_num, gains=gains))
                continue

            if current_rule is not None:
                gains = _parse_resource_amount(line)
                for r, a in gains.items():
                    current_gains[r] = current_gains.get(r, 0) + a

    if current_rule is not None and current_gains:
        rules.append(GainRule(rule_type=current_rule, gains=current_gains.copy()))

    store.gain_rules = rules
    store.day_overrides = day_overrides


def _load_initial_resources(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'initial_resources.txt')
    if not os.path.exists(filepath):
        return

    store.initial_resources = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('|')
                if len(parts) >= 2:
                    rid = parts[0].strip()
                    try:
                        amt = float(parts[1].strip())
                    except ValueError:
                        continue
                    store.initial_resources[rid] = store.initial_resources.get(rid, 0) + amt
    except FileNotFoundError:
        pass


def _load_targets(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'targets.txt')
    if not os.path.exists(filepath):
        return

    store.target_cards = []
    merged = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('|')
                card_id = parts[0].strip()
                quantity = 1
                pool_ids = []
                if len(parts) >= 2:
                    try:
                        quantity = int(parts[1].strip())
                    except ValueError:
                        pass
                if len(parts) >= 3 and parts[2].strip():
                    pool_ids = [p.strip() for p in parts[2].split(',') if p.strip()]
                if card_id in merged:
                    existing = merged[card_id]
                    existing.quantity = max(existing.quantity, quantity)
                    for pid in pool_ids:
                        if pid not in existing.pool_ids:
                            existing.pool_ids.append(pid)
                else:
                    merged[card_id] = TargetCardEntry(
                        card_id=card_id, quantity=quantity, pool_ids=pool_ids,
                    )
    except FileNotFoundError:
        pass
    store.target_cards = list(merged.values())


def _parse_resource_amount(text: str) -> Dict[str, float]:
    result = {}
    for part in text.split(','):
        part = part.strip()
        if ':' in part:
            rid, amt = part.split(':', 1)
            result[rid.strip()] = float(amt.strip())
    return result


def _save_resources(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'resources.txt')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("# Resource Type Definitions\n")
        f.write("# Format: resource_id | display_name\n\n")
        for rid, name in store.resource_defs.items():
            f.write(f"{rid} | {name}\n")


def _save_cards(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'cards.txt')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("# Card Definitions\n")
        f.write("# Format: card_id | name | rarity | [initial_count]\n\n")
        for cd in store.card_defs:
            pools_str = ','.join(cd.pools) if cd.pools else ''
            if getattr(cd, 'initial_count', 0) > 0:
                f.write(f"{cd.card_id} | {cd.name} | {cd.rarity} | {cd.initial_count}\n")
            else:
                f.write(f"{cd.card_id} | {cd.name} | {cd.rarity}\n")


def _save_schedule(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'schedule.txt')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("# Pool Schedule Configuration\n")
        f.write("# Format: pool_id | name | start_day | end_day | cost | template | bindings | target_card_ids\n\n")
        for pool in store.pools:
            if not pool.enabled:
                continue
            dist_file = pool.distribution_file or f"pools/{pool.pool_id}.txt"
            bindings_parts = []
            for k, v in pool.bindings.items():
                bindings_parts.append(f"{k}={v}")
            if pool.rerun_of:
                bindings_parts.append(f"rerun_of={pool.rerun_of}")
            if pool.exchange_card_id:
                bindings_parts.append(f"exchange_card={pool.exchange_card_id}")
            bindings_str = ';'.join(bindings_parts)

            target_parts = []
            for cid, qty in pool.target_specs:
                if qty > 1:
                    target_parts.append(f"{cid}:{qty}")
                else:
                    target_parts.append(cid)
            target_str = ','.join(target_parts)

            f.write(f"{pool.pool_id} | {pool.name} | {pool.start_day} | {pool.end_day} | {pool.cost} | {dist_file} | {bindings_str} | {target_str}\n")


def _save_pity(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'pity.txt')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("# Pity Configuration\n")
        f.write("# Format: pity: name | type=soft|hard | params... | target=... | reset=... | pools=...\n\n")
        if not store.pity.enabled:
            f.write("# Pity disabled\n")
            return

        for p in store.pity.pities:
            parts = [p.name, f"type={p.btype}"]
            for k, v in p.params.items():
                parts.append(f"{k}={v}")
            if p.target_distribution:
                target_parts = [f"{cid}:{w}" for cid, w in p.target_distribution.items()]
                parts.append(f"target={','.join(target_parts)}")
            parts.append(f"reset={p.reset_condition}")
            parts.append(f"pools={p.pools}")
            f.write(f"pity: {' | '.join(parts)}\n")


def _save_gains(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'gains.txt')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("# Resource Gain Schedule\n")
        f.write("# Format: [rule_type] followed by resource_id: amount lines\n")
        f.write("# day: day_number | resource_id: amount\n\n")
        for rule in store.gain_rules:
            f.write(f"[{rule.rule_type}]\n")
            for rid, amt in rule.gains.items():
                f.write(f"{rid}: {amt}\n")
            f.write("\n")

        if store.day_overrides:
            f.write("# === Day Overrides ===\n")
            for do in store.day_overrides:
                gains_str = ', '.join(f"{rid}: {amt}" for rid, amt in do.gains.items())
                f.write(f"day: {do.day} | {gains_str}\n")


def _save_initial_resources(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'initial_resources.txt')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("# Initial Resources\n")
        f.write("# Format: resource_id | amount\n\n")
        for rid, amt in store.initial_resources.items():
            f.write(f"{rid} | {amt}\n")


def _save_targets(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'targets.txt')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("# Target Cards\n")
        f.write("# Format: card_id | quantity | pool_ids(comma separated)\n\n")
        for tc in store.target_cards:
            pools_str = ','.join(tc.pool_ids) if tc.pool_ids else ''
            f.write(f"{tc.card_id} | {tc.quantity} | {pools_str}\n")


def _save_distributions(dir_path: str, store: ConfigStore):
    pools_dir = os.path.join(dir_path, 'pools')
    os.makedirs(pools_dir, exist_ok=True)

    saved_files = set()
    for pool in store.pools:
        if not pool.enabled or not pool.distribution:
            continue
        dist_file = pool.distribution_file or f"pools/{pool.pool_id}.txt"
        if os.path.isabs(dist_file):
            continue

        if dist_file in saved_files:
            continue
        saved_files.add(dist_file)

        dist_path = os.path.join(dir_path, dist_file)
        os.makedirs(os.path.dirname(dist_path), exist_ok=True)

        with open(dist_path, 'w', encoding='utf-8') as f:
            f.write(f"# Distribution for {pool.pool_id}\n\n")
            for entry in pool.distribution:
                prob_str = f"{entry.probability:.4f}"
                f.write(f"{entry.card_id} | {prob_str} | {entry.rarity}")
                if entry.featured:
                    f.write(" | featured")
                if entry.resources_gained:
                    rg_str = ', '.join(f"{k}:{v}" for k, v in entry.resources_gained.items())
                    f.write(f" | {rg_str}")
                elif entry.first_time_bonus or entry.nth_time_bonus or entry.excess_bonus:
                    f.write(" | ")
                if getattr(entry, 'first_time_bonus', None):
                    ft_str = ', '.join(f"{k}:{v}" for k, v in entry.first_time_bonus.items())
                    f.write(f" | ft:{ft_str}")
                if getattr(entry, 'nth_time_bonus', None):
                    parts = []
                    for nth, res in sorted(entry.nth_time_bonus.items()):
                        res_str = ','.join(f"{k}:{v}" for k, v in res.items())
                        parts.append(f"{nth}={res_str}")
                    f.write(f" | nth:{';'.join(parts)}")
                if getattr(entry, 'excess_bonus', None):
                    threshold = entry.excess_bonus.get('threshold', 999999)
                    res = entry.excess_bonus.get('resources', {})
                    res_str = ','.join(f"{k}:{v}" for k, v in res.items())
                    f.write(f" | xs:{threshold}>{res_str}")
                f.write('\n')


def _load_weights(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'weights.txt')
    if not os.path.exists(filepath):
        return

    store.card_weights = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('|')
                if len(parts) < 2:
                    continue
                card_id = parts[0].strip()
                desire_weight = 1.0
                miss_cost_weight = 1.0
                card_value = 1.0
                if len(parts) >= 2:
                    try:
                        desire_weight = float(parts[1].strip())
                    except ValueError:
                        pass
                if len(parts) >= 3:
                    try:
                        miss_cost_weight = float(parts[2].strip())
                    except ValueError:
                        pass
                if len(parts) >= 4:
                    try:
                        card_value = float(parts[3].strip())
                    except ValueError:
                        pass
                store.card_weights[card_id] = CardWeightEntry(
                    desire_weight=desire_weight,
                    miss_cost_weight=miss_cost_weight,
                    card_value=card_value,
                )
    except FileNotFoundError:
        pass


def _save_weights(dir_path: str, store: ConfigStore):
    filepath = os.path.join(dir_path, 'weights.txt')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("# Card Weight Configuration\n")
        f.write("# Format: card_id | desire_weight | miss_cost_weight | card_value\n\n")
        for card_id, cw in store.card_weights.items():
            f.write(f"{card_id} | {cw.desire_weight} | {cw.miss_cost_weight} | {cw.card_value}\n")
