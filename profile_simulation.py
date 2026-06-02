#!/usr/bin/env python3
"""性能分析：测量 GUI 模拟流程各阶段耗时"""
import sys, os, time

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gacha_simulator.core.config_io import load_store_from_directory
from gacha_simulator.service.batch_simulator import (
    SimulationEnvBuilder, run_batch_parallel,
)
from gacha_simulator.core.streaming import SharedResultCollector, extract_aggregate

# 1. 加载配置
t0 = time.time()
config_dir = os.path.join(os.path.dirname(__file__), 'gacha_simulator', 'config')
config_store = load_store_from_directory(config_dir)
t1 = time.time()
print(f"[1] 加载配置: {t1 - t0:.3f}s")

# 2. 构建 SimulationEnv
target_specs = {tc.card_id: tc.quantity for tc in config_store.target_cards}
N = 1000
max_workers = min(16, (os.cpu_count() or 8) - 2)

env = SimulationEnvBuilder.from_config_store(config_store)
t2 = time.time()
print(f"[2] 构建 SimulationEnv: {t2 - t1:.3f}s")

# 3. 运行批量模拟
env.n_heatmap_bins = max(20, min(100, int(N ** 0.5)))

collector = SharedResultCollector()
collector.add_extractor('aggregate', extract_aggregate)

first_progress_time = [None]
progress_samples = []

def progress_callback(done, total):
    now = time.time()
    if first_progress_time[0] is None:
        first_progress_time[0] = now
        print(f"    [首次进度] done={done}/{total} @ {now - t2:.3f}s (距env构建)")
    progress_samples.append((now - t2, done))

print(f"\n[3] 启动批量模拟: N={N}, workers={max_workers}")

t3 = time.time()
batch_result = run_batch_parallel(
    env=env, target_specs=target_specs,
    initial_resources=env.initial_resources,
    num_simulations=N, max_workers=max_workers, seed=42,
    progress_callback=progress_callback,
    strategy_name=config_store.strategy_name,
    strategy_params=config_store.strategy_params,
    on_result=collector.on_result,
)
t4 = time.time()

print(f"\n=== 耗时统计 ===")
print(f"  env构建:            {t2 - t1:.2f}s")
print(f"  首次进度回调(距env): {first_progress_time[0] - t2:.2f}s")
print(f"  首次进度回调(距run):  {first_progress_time[0] - t3:.2f}s")
print(f"  模拟总耗时:          {t4 - t3:.2f}s")
print(f"  全程:               {t4 - t0:.2f}s")

if len(progress_samples) >= 2:
    ps = sorted(progress_samples, key=lambda x: x[0])
    first_t = ps[0][0]
    last_t = ps[-1][0]
    print(f"  进度更新次数:        {len(progress_samples)}")
    print(f"  进度条活跃期:        {last_t - first_t:.2f}s")
    print(f"  最终进度:           {ps[-1][1]}/{N}")

# 4. 单次模拟耗时
from gacha_simulator.core import GachaState, TargetCard, TargetCardSet
from gacha_simulator.service import GachaService
from gacha_simulator.core.stop_condition import AllPoolsEndCondition
from gacha_simulator.core.strategy import create_strategy
from gacha_simulator.core.pity import PityState
import random, numpy as np

card_def_map = {c['card_id']: c for c in env.card_defs} if env.card_defs else {}
targets = []
for card_id, qty in target_specs.items():
    pools = card_def_map.get(card_id, {}).get('pools', [])
    targets.append(TargetCard(card_id=card_id, pool_ids=pools, quantity_needed=qty))
target_set = TargetCardSet(targets)

random.seed(42)
strategy = create_strategy(env.strategy_name, env.strategy_params)
stop_cond = AllPoolsEndCondition(env.end_time)
pity_state = None
if env.pity_state_init:
    pity_state = PityState()
    for cname, cval in env.pity_state_init.get('counters', {}).items():
        pity_state.counters[cname] = cval

service = GachaService(
    env.pools, strategy, stop_cond, target_set,
    schedule_manager=env.schedule_mgr, pity_engine=env.pity_engine,
    resource_gain=env.resource_gain, pity_state=pity_state,
    ssr_ids=env.ssr_ids, card_defs=env.card_defs,
)

print(f"\n[4] 单次模拟预热...")
# warmup
_ = service.run_simulation_compact(GachaState(resources=dict(env.initial_resources)))

sim_times = []
for i in range(10):
    rs = time.time()
    _ = service.run_simulation_compact(GachaState(resources=dict(env.initial_resources)))
    sim_times.append(time.time() - rs)

print(f"  10次: min={min(sim_times)*1000:.0f}ms max={max(sim_times)*1000:.0f}ms avg={np.mean(sim_times)*1000:.0f}ms")

chunksize = max(1, N // (max_workers * 16))
print(f"\n[5] 参数: workers={max_workers}, chunksize={chunksize}")
print(f"  首个chunk纯模拟耗时: ~{np.mean(sim_times) * chunksize:.1f}s")
print(f"  估计setup开销: {first_progress_time[0] - t3 - np.mean(sim_times) * chunksize:.1f}s")
