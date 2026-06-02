#!/usr/bin/env python3
"""GUI 模拟性能实测 —— 使用与 GUI 界面完全一致的代码路径。

模拟真实使用场景：
  Phase A: 应用启动（MainWindow 初始化 + 所有面板导入 + 配置加载）
  Phase B: 首次点击「开始模拟」（from_config_store -> 模拟 -> 分发）
  Phase C: 第二次点击（热启动，import 缓存已预热）

运行方式：python profile_gui.py
"""

import sys, os, time, gc

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def fmt(seconds):
    if seconds < 0.01:
        return f"{seconds*1000:.1f}ms"
    return f"{seconds:.2f}s"


def header(title):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")


def sub_stage(name, value):
    print(f"  {name:<50} {fmt(value):>10}")


def sep():
    print(f"  {'-'*60}")


# ── 辅助函数：单次模拟周期 ──
def run_simulation_cycle(store, N, max_workers, label):
    import numpy as np

    from gacha_simulator.gui.batch_simulator import (
        SimulationEnvBuilder, run_batch_parallel,
    )
    from gacha_simulator.core.streaming import (
        SharedResultCollector, extract_aggregate,
    )

    times = {}
    gc.collect()

    # B1: from_config_store
    t0 = time.perf_counter()
    env = SimulationEnvBuilder.from_config_store(store)
    t1 = time.perf_counter()
    times['B1_from_config_store'] = t1 - t0

    # B2: 准备参数
    target_specs = {tc.card_id: tc.quantity for tc in store.target_cards}
    n_heatmap_bins = max(20, min(100, int(N ** 0.5)))
    env.n_heatmap_bins = n_heatmap_bins

    collector = SharedResultCollector()
    collector.add_extractor('aggregate', extract_aggregate)
    t2 = time.perf_counter()
    times['B2_准备参数'] = t2 - t1

    # B3: 主模拟
    first_progress = [None]
    progress_count = [0]

    def on_progress(done, total):
        now = time.perf_counter()
        if first_progress[0] is None:
            first_progress[0] = now
        progress_count[0] += 1

    batch_result = run_batch_parallel(
        env=env,
        target_specs=target_specs,
        initial_resources=env.initial_resources,
        num_simulations=N,
        max_workers=max_workers,
        seed=42,
        progress_callback=on_progress,
        strategy_name=store.strategy_name,
        strategy_params=store.strategy_params,
        on_result=collector.on_result,
    )
    t3 = time.perf_counter()
    times['B3a_主模拟_总耗时'] = t3 - t2
    times['B3b_其中_首次进度前等待'] = (
        first_progress[0] - t2 if first_progress[0] else 0
    )
    times['B3c_其中_活跃模拟期'] = (
        t3 - first_progress[0] if first_progress[0] else 0
    )
    times['B3d_进度信号次数'] = progress_count[0]

    # B4: no_draw 基线
    t4_start = time.perf_counter()
    no_draw_resource = None
    no_draw_pool_resources = {}
    try:
        no_draw_results = run_batch_parallel(
            env=env,
            target_specs=target_specs,
            initial_resources=env.initial_resources,
            num_simulations=1,
            max_workers=1,
            seed=42,
            strategy_name='no_draw',
        )
        if no_draw_results and len(no_draw_results) > 0:
            r0 = no_draw_results[0]
            if isinstance(r0, dict):
                no_draw_resource = r0.get('final_resources', {}).get(
                    'draw_resource', None)
                no_draw_pool_resources = r0.get('pool_end_resources', {})
    except Exception:
        pass
    t4 = time.perf_counter()
    times['B4_no_draw基线'] = t4 - t4_start

    # B5: 构建 result_bundle
    t5_start = time.perf_counter()
    ext = getattr(batch_result, 'extraction', None)
    if ext is not None:
        heatmap_bins = {
            'achievement': np.linspace(0, 1.05, n_heatmap_bins + 1),
            'resource': np.linspace(
                0, max(env.initial_resources.get('draw_resource', 0), 1.0) * 2,
                n_heatmap_bins + 1,
            ),
        }
        result_bundle = {
            'aggregate_data': ext.get('aggregates', []),
            'draw_sequences': ext.get('kept_sequences', []),
            'heatmap_data': {
                'data': {
                    'achievement': ext.get('heatmap_ach', {}),
                    'resource': ext.get('heatmap_res', {}),
                },
                'bins': heatmap_bins,
            },
            'cumulative_snapshots': ext.get('cumulative_snapshots', {}),
            'transition_flags': ext.get('transition_flags', []),
            'target_ids': env.target_ids,
            'ssr_ids': env.ssr_ids,
            'gdr_context': env.gdr_context,
            'pool_end_times': env.pool_end_times,
            'target_specs': target_specs,
            'n_results': ext.get('n_results', 0),
            'n_requested': N,
            'no_draw_resource': no_draw_resource,
            'no_draw_pool_resources': no_draw_pool_resources,
        }
    else:
        result_bundle = {
            'aggregate_data': collector.get_extracted('aggregate'),
            'draw_sequences': [],
            'heatmap_data': {'data': {}, 'bins': {}},
            'cumulative_snapshots': {},
            'transition_flags': [],
            'target_ids': env.target_ids,
            'ssr_ids': env.ssr_ids,
            'gdr_context': env.gdr_context,
            'pool_end_times': env.pool_end_times,
            'target_specs': target_specs,
            'n_results': collector.n_results,
            'n_requested': N,
            'no_draw_resource': no_draw_resource,
            'no_draw_pool_resources': no_draw_pool_resources,
        }
    t5 = time.perf_counter()
    times['B5_构建result_bundle'] = t5 - t5_start

    # B6: 面板分发 (MainWindow.on_simulation_finished)
    t6_start = time.perf_counter()
    aggregate_data = result_bundle.get('aggregate_data', [])
    target_ids = result_bundle.get('target_ids', set())
    ssr_ids = result_bundle.get('ssr_ids', set())
    gdr_context = result_bundle.get('gdr_context', None)
    pool_end_times = result_bundle.get('pool_end_times', {})
    draw_sequences = result_bundle.get('draw_sequences', [])
    heatmap_data = result_bundle.get('heatmap_data', {})
    cumulative_snapshots = result_bundle.get('cumulative_snapshots', {})
    transition_flags = result_bundle.get('transition_flags', [])

    from gacha_simulator.gui.analysis_panel import AnalysisPanel
    from gacha_simulator.gui.worst_impact_panel import WorstImpactPanel
    from gacha_simulator.gui.retreat_panel import RetreatPanel
    from gacha_simulator.gui.process_analysis_panel import ProcessAnalysisPanel

    analysis_panel = AnalysisPanel()
    analysis_panel.set_store(store)
    worst_impact_panel = WorstImpactPanel()
    worst_impact_panel.set_store(store)
    retreat_panel = RetreatPanel()
    retreat_panel.set_store(store)
    process_analysis_panel = ProcessAnalysisPanel()

    ta = time.perf_counter()
    analysis_panel.update_results(
        aggregate_data,
        draw_sequences=draw_sequences,
        heatmap_data=heatmap_data,
        cumulative_snapshots=cumulative_snapshots,
        transition_flags=transition_flags,
        target_ids=target_ids,
        ssr_ids=ssr_ids,
        gdr_context=gdr_context,
        pool_end_times=pool_end_times,
        no_draw_resource=no_draw_resource,
        no_draw_pool_resources=no_draw_pool_resources,
    )
    times['B6a_analysis_panel'] = time.perf_counter() - ta

    tb = time.perf_counter()
    worst_impact_panel.set_simulation_results(aggregate_data, target_specs)
    worst_impact_panel._load_last_pool_config()
    times['B6b_worst_impact_panel'] = time.perf_counter() - tb

    tc = time.perf_counter()
    retreat_panel.set_simulation_results(
        aggregate_data, target_specs,
        no_draw_resource=no_draw_resource,
        no_draw_pool_resources=no_draw_pool_resources,
    )
    times['B6c_retreat_panel'] = time.perf_counter() - tc

    td = time.perf_counter()
    pool_types = {}
    for pe in store.pools:
        pool_type = pe.bindings.get('type', '角色') if pe.bindings else '角色'
        pool_types[pe.pool_id] = pool_type
    initial_resources = (
        getattr(gdr_context, 'initial_resources', {}) if gdr_context else {}
    )
    process_analysis_panel.update_results(
        aggregate_data,
        target_ids=target_ids,
        ssr_ids=ssr_ids,
        gdr_context=gdr_context,
        target_specs=target_specs,
        pool_end_times=pool_end_times,
        initial_resources=initial_resources,
        cumulative_snapshots=cumulative_snapshots,
        pool_types=pool_types,
    )
    times['B6d_process_analysis_panel'] = time.perf_counter() - td

    t6 = time.perf_counter()
    times['B6_面板分发_总耗时'] = t6 - t6_start

    analysis_panel.deleteLater()
    worst_impact_panel.deleteLater()
    retreat_panel.deleteLater()
    process_analysis_panel.deleteLater()

    times['总耗时'] = t6 - t0
    times['模拟线程耗时'] = t5 - t0
    times['其中_pool创建+首次进度'] = (
        times['B1_from_config_store'] + times['B2_准备参数'] +
        times['B3b_其中_首次进度前等待']
    )
    return times


def print_cycle(times, label):
    header(label)
    items = [
        ('B1_from_config_store',        'B1. from_config_store'),
        ('B2_准备参数',                  'B2. 准备参数'),
        ('B3a_主模拟_总耗时',            'B3. 主模拟 - 总耗时'),
        ('B3b_其中_首次进度前等待',      '  B3b. 首次进度前等待 (用户感知)'),
        ('B3c_其中_活跃模拟期',          '  B3c. 进度条活跃期'),
        ('B3d_进度信号次数',             '  B3d. 进度信号发射次数'),
        ('B4_no_draw基线',              'B4. no_draw 基线'),
        ('B5_构建result_bundle',        'B5. 构建 result_bundle'),
        ('B6_面板分发_总耗时',           'B6. 面板分发 - 总耗时'),
        ('B6a_analysis_panel',          '  B6a. analysis_panel'),
        ('B6b_worst_impact_panel',      '  B6b. worst_impact_panel'),
        ('B6c_retreat_panel',           '  B6c. retreat_panel'),
        ('B6d_process_analysis_panel',  '  B6d. process_analysis_panel'),
    ]
    for key, display in items:
        val = times.get(key)
        if val is None:
            continue
        if '次数' in display:
            print(f"  {display:<50} {int(val):>10}")
        else:
            print(f"  {display:<50} {fmt(val):>10}")
    sep()
    print(f"  {'模拟线程耗时 (B1->B5)':<50} {fmt(times.get('模拟线程耗时', 0)):>10}")
    print(f"  {'其中: 创建+首次进度前等待':<50} {fmt(times.get('其中_pool创建+首次进度', 0)):>10}")
    print(f"  {'周期总耗时 (B1->B6)':<50} {fmt(times.get('总耗时', 0)):>10}")


# ═══════════════════════════════════════════════════════════════
# 主程序 - 必须在 __main__ 护卫内
# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    from multiprocessing import freeze_support
    freeze_support()

    # Windows GBK
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    # ═══════════════════════════════════════════════════════════
    # Phase A: 模拟应用启动
    # ═══════════════════════════════════════════════════════════
    header("Phase A: 应用启动 (模拟 MainWindow.__init__)")

    ta0 = time.perf_counter()

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    _app = QApplication(sys.argv)
    ta1 = time.perf_counter()
    sub_stage("A1. QApplication 初始化", ta1 - ta0)

    ta2_start = time.perf_counter()
    from gacha_simulator.gui.main_window import MainWindow
    ta2 = time.perf_counter()
    sub_stage("A2. 导入 MainWindow + 所有面板", ta2 - ta2_start)

    ta3_start = time.perf_counter()
    from gacha_simulator.core.config_io import load_store_from_directory
    from gacha_simulator.core.config_store import ConfigStore
    ta3 = time.perf_counter()
    sub_stage("A3. 导入 config_io + ConfigStore", ta3 - ta3_start)

    ta4_start = time.perf_counter()
    config_dir = os.path.join(
        os.path.dirname(__file__), 'gacha_simulator', 'config')
    store = ConfigStore()
    load_store_from_directory(config_dir, store)
    ta4 = time.perf_counter()
    sub_stage("A4. 加载配置", ta4 - ta4_start)

    sub_stage("Phase A 合计 (应用启动到可操作)", ta4 - ta0)

    # ═══════════════════════════════════════════════════════════
    # Phase B + C: 模拟周期
    # ═══════════════════════════════════════════════════════════
    print(f"\nGachaStat GUI 模拟性能实测")
    print(f"平台: win32 | CPU: {os.cpu_count()} 核")
    N = 1000
    max_workers = min(16, (os.cpu_count() or 8) - 2)
    print(f"参数: N={N}, workers={max_workers}")

    header("Phase B: 首次点击「开始模拟」(冷启动)")
    print("  (含首次 import GachaService/GachaState 等核心类)")
    cold = run_simulation_cycle(store, N, max_workers, "冷启动")
    print_cycle(cold, "首次点击耗时明细")

    header("Phase C: 第二次点击 (热启动)")
    print("  (所有 import 已缓存，仅剩运行时开销)")
    warm = run_simulation_cycle(store, N, max_workers, "热启动")
    print_cycle(warm, "第二次点击耗时明细")

    # ═══════════════════════════════════════════════════════════
    # 综合分析
    # ═══════════════════════════════════════════════════════════
    header("综合分析")

    print(f"\n  [用户体验时间线 - 首次点击]")
    print(f"  {'应用启动':<24} {fmt(ta4 - ta0):>10}")
    print(f"  {'点击->首次进度':<24} {fmt(cold['其中_pool创建+首次进度']):>10}")
    print(f"  {'进度条活跃期':<24} {fmt(cold['B3c_其中_活跃模拟期']):>10}")
    print(f"  {'完成后分发面板':<24} {fmt(cold['B6_面板分发_总耗时']):>10}")
    print(f"  {'从点击到完成':<24} {fmt(cold['总耗时']):>10}")

    print(f"\n  [用户体验时间线 - 第二次点击]")
    print(f"  {'点击->首次进度':<24} {fmt(warm['其中_pool创建+首次进度']):>10}")
    print(f"  {'进度条活跃期':<24} {fmt(warm['B3c_其中_活跃模拟期']):>10}")
    print(f"  {'完成后分发面板':<24} {fmt(warm['B6_面板分发_总耗时']):>10}")
    print(f"  {'从点击到完成':<24} {fmt(warm['总耗时']):>10}")

    print(f"\n  [瓶颈排名 (首次点击)]")
    bottlenecks = [
        ("首次进度前等待 (spawn+import+首个chunk)", cold['B3b_其中_首次进度前等待']),
        ("活跃模拟期 (16 worker 并行)", cold['B3c_其中_活跃模拟期']),
        ("from_config_store", cold['B1_from_config_store']),
        ("面板分发", cold['B6_面板分发_总耗时']),
        ("no_draw基线", cold['B4_no_draw基线']),
        ("构建result_bundle", cold['B5_构建result_bundle']),
        ("准备参数", cold['B2_准备参数']),
    ]
    bottlenecks.sort(key=lambda x: -x[1])
    for i, (name, val) in enumerate(bottlenecks, 1):
        bar = '#' * int(val / cold['总耗时'] * 40) if cold['总耗时'] > 0 else ''
        print(f"  {i}. {name:<40} {fmt(val):>10}  {bar}")

    print(f"\n  [可优化空间评估]")
    total = cold['总耗时']
    sim = cold['B3c_其中_活跃模拟期']
    setup = total - sim
    print(f"  总耗时: {fmt(total)}")
    print(f"  纯模拟计算: {fmt(sim)} ({sim/total*100:.0f}%)")
    print(f"  非模拟开销: {fmt(setup)} ({setup/total*100:.0f}%)")
    print(f"  -- 可优化部分 --")
    print(f"  首次进度前等待 (可缩短但无法消除): {fmt(cold['B3b_其中_首次进度前等待'])}")
    print(f"  面板分发 (可延迟加载): {fmt(cold['B6_面板分发_总耗时'])}")

    print(f"\n== 实测完成 ==")
