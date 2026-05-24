#!/usr/bin/env python3
"""GachaStat 命令行版本"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from gacha_simulator.core import (
    Pool, Reward, GachaState, DrawAction, WaitAction,
    TargetCard, TargetCardSet, PoolSchedule, PoolScheduleManager
)
from gacha_simulator.core.pool import parse_cost_string
from gacha_simulator.core.stop_condition import StopCondition
from gacha_simulator.core.pity import (
    PityEngine, PityState, PoolPitySpec,
    PityDefParsed, SoftPityBehavior, HardPityBehavior,
)
from gacha_simulator.service import GachaService
from gacha_simulator.core.generalized_drop_rate import TargetCardCountAtT, TargetCardPercentageAtT
from multiprocessing import Pool as MPPool


DAY = 86400


def create_pools_from_config(config):
    pools = []
    targets = []
    schedules = []
    
    for p in config['pools']:
        ssr = Reward(f"{p['id']}_ssr", f"{p['name']}SSR", {})
        sr = Reward(f"{p['id']}_sr", f"{p['name']}SR", {})
        r = Reward(f"{p['id']}_r", f"{p['name']}R", {})
        
        ssr_rate = p.get('ssr_rate', 0.006)
        sr_rate = p.get('sr_rate', 0.051)
        r_rate = max(0.0, 1 - ssr_rate - sr_rate)
        
        pool = Pool(
            id=p['id'], name=p['name'],
            cost=parse_cost_string(f"draw_resource:{p['cost']}"),
            rewards=[(ssr, ssr_rate), (sr, sr_rate), (r, r_rate)],
            available_from=p['start_day'] * DAY,
            available_until=(p['start_day'] + p['duration']) * DAY,
        )
        pools.append(pool)
        targets.append(TargetCard(
            card_id=f"{p['id']}_ssr", pool_ids=[p['id']], 
            quantity_needed=1, priority=0
        ))
        schedules.append(PoolSchedule(
            pool_id=p['id'],
            available_from=p['start_day'] * DAY,
            available_until=(p['start_day'] + p['duration']) * DAY,
        ))
    
    return pools, TargetCardSet(targets), PoolScheduleManager(schedules)


def create_pity_engine_from_config(config, pools):
    pity_config = config.get('pity', {})
    if not pity_config.get('enabled', True):
        return None

    pities_cfg = pity_config.get('pities', [])

    pity_defs = {}
    behaviors = {}
    for p in pities_cfg:
        name = p.get('name', 'pity')
        btype = p.get('type', 'soft')
        target_dist = p.get('target_distribution', {})
        reset = p.get('reset', 'any_ssr')
        pools_pattern = p.get('pools', '*')
        params = p.get('params', {})

        pdef = PityDefParsed(
            name=name,
            btype=btype,
            params=params,
            target_distribution=target_dist,
            reset_condition=reset,
            pools=pools_pattern,
        )
        pity_defs[name] = pdef

        if btype == 'soft':
            behaviors[name] = SoftPityBehavior(
                start_at=int(params.get('start', '74')),
                end_at=int(params.get('end', '90')),
                func_type=params.get('func', 'linear'),
                target_distribution=target_dist,
            )
        elif btype == 'hard':
            behaviors[name] = HardPityBehavior(
                threshold=int(params.get('threshold', '90')),
                target_distribution=target_dist,
            )

    pool_specs = {}
    import fnmatch
    for pool in pools:
        pid = pool.id
        featured = set()
        ssr_all = set()
        if pool.rewards:
            featured.add(pool.rewards[0][0].id)
            ssr_all.add(pool.rewards[0][0].id)
            if len(pool.rewards) > 1:
                ssr_all.add(pool.rewards[1][0].id)

        matching = []
        for pdef in pity_defs.values():
            if fnmatch.fnmatch(pid, pdef.pools):
                matching.append(pdef.name)

        pool_specs[pid] = PoolPitySpec(
            pity_names=matching,
            featured_ids=featured,
            ssr_ids=ssr_all,
        )

    return PityEngine(pool_specs, pity_defs, behaviors)


class SmartStrategy:
    lookahead = None

    def __init__(self, target_cards):
        self.target_cards = target_cards
        self.acquired = {}
        self._pool_to_targets = {}
        for t in target_cards.targets:
            for pid in t.pool_ids:
                self._pool_to_targets.setdefault(pid, []).append(t)

    def _pool_needs_target(self, pool_id):
        for t in self._pool_to_targets.get(pool_id, []):
            if self.acquired.get(t.card_id, 0) < t.quantity_needed:
                return True
        return False

    def select_action(self, state, history, current_pools, future_schedules, target_cards, stop_cond):
        for pool in current_pools:
            if self._pool_needs_target(pool.id) and state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)

        wait_time = DAY
        for pool in current_pools:
            if pool.available_until and pool.available_until > state.real_time:
                wait_time = min(wait_time, pool.available_until - state.real_time)

        if wait_time <= 0:
            wait_time = 3600

        return WaitAction(duration=wait_time)

    @classmethod
    def description(cls):
        return "按需追卡"


class AllPoolsEnd(StopCondition):
    def __init__(self, end_time):
        self.end_time = end_time
    
    def check(self, state, history, stats=None):
        return state.real_time >= self.end_time
    
    def description(self):
        return "所有池子结束"


def run_single_sim(args):
    import random
    pools, target_set, schedule_mgr, end_time, resources, seed, pity_engine = args
    random.seed(seed)

    strategy = SmartStrategy(target_set)
    stop_cond = AllPoolsEnd(end_time)
    service = GachaService(pools, strategy, stop_cond, target_set,
                          schedule_manager=schedule_mgr, pity_engine=pity_engine)
    state = GachaState(resources=resources.copy())
    return service.run_simulation_compact(state)


def main():
    parser = argparse.ArgumentParser(description='GachaStat CLI')
    parser.add_argument('-c', '--config', default='default_config.json', help='Config file path')
    parser.add_argument('-n', '--num-simulations', type=int, default=1000, help='Number of simulations')
    parser.add_argument('-w', '--workers', type=int, default=4, help='Number of parallel workers')
    parser.add_argument('-s', '--seed', type=int, default=42, help='Random seed')
    parser.add_argument('-o', '--output', default='results.json', help='Output file')
    parser.add_argument('--no-pity', action='store_true', help='Disable pity system')
    
    args = parser.parse_args()
    
    config_path = Path(args.config)
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
    else:
        config = {
            'pools': [
                {'id': f'pool_{i}', 'name': f'池子{i}', 'start_day': i*7, 'duration': 21, 
                 'cost': 160, 'ssr_rate': 0.015 if i < 4 else 0.007}
                for i in range(8)
            ],
            'pity': {'enabled': not args.no_pity, 'type': 'soft', 'start': 80, 'end': 90},
            'resources': {'draw_resource': 50000}
        }
    
    print("=" * 50)
    print("GachaStat CLI")
    print("=" * 50)
    print(f"Simulations: {args.num_simulations}")
    print(f"Workers: {args.workers}")
    print(f"Seed: {args.seed}")
    pity_cfg = config.get('pity', {})
    print(f"Pity: {'Enabled' if pity_engine else 'Disabled'}")
    if pity_engine:
        print(f"  Type: {pity_cfg.get('type', 'soft')}")
        print(f"  Range: {pity_cfg.get('start', 80)}-{pity_cfg.get('end', 90)}")
    print("=" * 50)
    
    pools, target_set, schedule_mgr = create_pools_from_config(config)
    end_time = max(s.available_until for s in schedule_mgr.schedules)
    pity_engine = create_pity_engine_from_config(config, pools)
    
    resources = config.get('resources', {'draw_resource': 50000})
    
    args_list = [
        (pools, target_set, schedule_mgr, end_time, resources,
         args.seed + i, pity_engine)
        for i in range(args.num_simulations)
    ]
    
    print(f"\nRunning {args.num_simulations} simulations...")
    start_time = time.time()
    
    with MPPool(processes=args.workers) as mp_pool:
        results = mp_pool.map(run_single_sim, args_list, chunksize=max(1, args.num_simulations // 100))
    
    elapsed = time.time() - start_time
    
    print(f"Completed in {elapsed:.2f}s ({args.num_simulations/elapsed:.1f} sim/s)")
    
    actual_target_ids = [t.card_id for t in target_set.targets]
    total_targets = len(actual_target_ids)

    total_draws = []
    ssr_counts = []
    gdr_percents = []

    for r in results:
        draws = r.get('total_draws', 0)
        total_draws.append(draws)
        cc = r.get('card_counts', {})
        ssr = sum(cc.get(tid, 0) for tid in actual_target_ids)
        ssr_counts.append(ssr)
        gdr_percents.append((ssr / max(total_targets, 1)) * 100)
    
    import numpy as np
    
    print("\n" + "=" * 50)
    print("Results Summary")
    print("=" * 50)
    print(f"Total Simulations: {len(results)}")
    print(f"\nTotal Draws:")
    print(f"  Mean: {np.mean(total_draws):.1f}")
    print(f"  Median: {np.median(total_draws):.1f}")
    print(f"  Std: {np.std(total_draws):.1f}")
    
    print(f"\nSSR Count:")
    print(f"  Mean: {np.mean(ssr_counts):.2f}")
    print(f"  Median: {np.median(ssr_counts):.1f}")
    
    print(f"\nGDR (Target Card %):")
    print(f"  Mean: {np.mean(gdr_percents):.2f}%")
    print(f"  Median: {np.median(gdr_percents):.2f}%")
    print(f"  25th percentile: {np.percentile(gdr_percents, 25):.2f}%")
    print(f"  75th percentile: {np.percentile(gdr_percents, 75):.2f}%")
    
    output_data = {
        'config': config,
        'num_simulations': args.num_simulations,
        'elapsed_time': elapsed,
        'summary': {
            'total_draws': {'mean': float(np.mean(total_draws)), 'median': float(np.median(total_draws))},
            'ssr_counts': {'mean': float(np.mean(ssr_counts)), 'median': float(np.median(ssr_counts))},
            'gdr_percent': {
                'mean': float(np.mean(gdr_percents)),
                'median': float(np.median(gdr_percents)),
                'p25': float(np.percentile(gdr_percents, 25)),
                'p75': float(np.percentile(gdr_percents, 75))
            }
        }
    }
    
    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\nResults saved to: {args.output}")
    print("=" * 50)


if __name__ == '__main__':
    main()
