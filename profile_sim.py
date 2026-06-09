#!/usr/bin/env python3
"""性能分析：模拟 GUI 流程各阶段耗时"""
import sys, os, time

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from gacha_simulator.core.config_io import load_store_from_directory
    from gacha_simulator.service.batch_simulator import (
        SimulationEnvBuilder, run_batch_parallel,
    )
    from gacha_simulator.core.streaming import SharedResultCollector, extract_aggregate

    # ── 加载配置 ──
    t0 = time.time()
    config_store = load_store_from_directory(os.path.join(
        os.path.dirname(__file__), 'gacha_simulator', 'config'))
    print(f"[1] 加载配置: {time.time() - t0:.2f}s")

    # ── 构建 SimulationEnv ──
    t1 = time.time()
    target_specs = {tc.card_id: tc.quantity for tc in config_store.target_cards}
    N, workers = 1000, min(16, (os.cpu_count() or 8) - 2)
    env = SimulationEnvBuilder.from_config_store(config_store)
    t2 = time.time()
    print(f"[2] env构建: {t2 - t1:.2f}s")

    # ── 批量模拟 ──
    env.n_heatmap_bins = 50
    collector = SharedResultCollector()
    collector.add_extractor('aggregate', extract_aggregate)

    first_ts = [None]
    pbar_times = []

    def on_progress(done, total):
        now = time.time()
        if first_ts[0] is None:
            first_ts[0] = now
            print(f"   [首次进度] done={done}/{total}  距env={now - t2:.1f}s  距run={now - t3_:.1f}s")
        pbar_times.append((now, done))

    print(f"\n[3] 启动批量模拟: N={N} workers={workers}")
    t3_ = time.time()
    result = run_batch_parallel(
        env=env, target_specs=target_specs, initial_resources=env.initial_resources,
        num_simulations=N, max_workers=workers, seed=42,
        progress_callback=on_progress,
        strategy_name=config_store.strategy_name,
        strategy_params=config_store.strategy_params,
        on_result=collector.on_result,
    )
    t4 = time.time()

    pbar_times.sort(key=lambda x: x[0])
    pfirst = pbar_times[0][0] if pbar_times else 0
    plast  = pbar_times[-1][0] if pbar_times else 0

    print(f"\n=== 耗时汇总 ===")
    print(f"  env构建:               {t2 - t1:.1f}s")
    print(f"  首次进度(距run调用):    {first_ts[0] - t3_:.1f}s")
    print(f"  模拟总耗时:             {t4 - t3_:.1f}s  ← 用户感知的等待")
    print(f"  其中: 进度前等待        {first_ts[0] - t3_:.1f}s")
    print(f"        进度条活跃期      {plast - pfirst:.1f}s  (更新{len(pbar_times)}次)")
    print(f"  全程(配置→完成):        {t4 - t0:.1f}s")

    # ── 单次模拟基准 ──
    from gacha_simulator.core import GachaState, TargetCard, TargetCardSet
    from gacha_simulator.service import GachaService
    from gacha_simulator.core.stop_condition import AllPoolsEndCondition
    from gacha_simulator.core.strategy import create_strategy
    from gacha_simulator.core.pity import PityState
    import random, numpy as np

    card_map = {c['card_id']: c for c in env.card_defs}
    targets = [TargetCard(card_id=cid, pool_ids=card_map[cid]['pools'], quantity_needed=qty)
               for cid, qty in target_specs.items()]
    tset = TargetCardSet(targets)
    strategy = create_strategy(env.strategy_name, env.strategy_params)
    stop = AllPoolsEndCondition(env.end_time)
    ps = None
    if env.pity_state_init:
        ps = PityState()
        for k, v in env.pity_state_init.get('counters', {}).items():
            ps.counters[k] = v
    svc = GachaService(env.pools, strategy, stop, tset,
                       schedule_manager=env.schedule_mgr, pity_engine=env.pity_engine,
                       resource_gain=env.resource_gain, pity_state=ps,
                       ssr_ids=env.ssr_ids, card_defs=env.card_defs)

    # 预热
    _ = svc.run_simulation_compact(GachaState(resources=dict(env.initial_resources)))
    times = []
    for _ in range(20):
        a = time.time()
        _ = svc.run_simulation_compact(GachaState(resources=dict(env.initial_resources)))
        times.append(time.time() - a)
    times = np.array(times)

    chunk = max(1, N // (workers * 16))
    print(f"\n[4] 参数: workers={workers} chunksize={chunk}")
    print(f"  单次模拟: avg={times.mean()*1000:.0f}ms  min={times.min()*1000:.0f}ms  max={times.max()*1000:.0f}ms")
    print(f"  chunk({chunk})纯模拟: ~{times.mean()*chunk:.1f}s")
    print(f"  推测setup开销: {first_ts[0] - t3_ - times.mean()*chunk:.1f}s  (进程创建+_wk_init+序列化)")

    # ── 对比：串行 ──
    print(f"\n[5] 串行对比 (单进程, 模拟10次):")
    t_s = time.time()
    for i in range(10):
        _ = svc.run_simulation_compact(GachaState(resources=dict(env.initial_resources)))
    t_e = time.time()
    print(f"  10次串行: {t_e - t_s:.1f}s → 1000次约 {(t_e-t_s)/10*1000:.0f}s")
    print(f"  并行加速比: 约 {(t_e-t_s)/10*1000/(t4-t3_):.1f}x")

if __name__ == '__main__':
    main()
