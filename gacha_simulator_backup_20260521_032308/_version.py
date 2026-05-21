__version__ = "1.9.0"

VERSION_DISPLAY = "v1.9.0"

VERSION_HISTORY = [
    ("1.0.0", "2026-05-07", "PROUD — 初始版本发布：核心模拟引擎、GUI、配置系统"),
    ("1.1.0", "2026-05-08", "DEFAULT — 分析面板、风险分析、经验分布"),
    ("1.1.1", "2026-05-09", "SHAME — 修复 ssr_ids 包含 SR 卡 ID 导致保底误判"),
    ("1.1.2", "2026-05-09", "SHAME — 修复 compact 模式 acquired 追踪失效"),
    ("1.1.3", "2026-05-10", "SHAME — 修复 pool_table.item() 返回 None 导致崩溃"),
    ("1.1.4", "2026-05-10", "SHAME — 修复分析面板摘要表全为 -（compact dict 未转换）"),
    ("1.2.0", "2026-05-13", "DEFAULT — 代码重构：统一模拟环境构建、GDR 成功率计算"),
    ("1.3.0", "2026-05-13", "DEFAULT — 退路分析：脆弱性分析、退路搜索、Pareto 前沿"),
    ("1.4.0", "2026-05-14", "DEFAULT — 最差影响分析、退路搜索二期"),
    ("1.5.0", "2026-05-16", "DEFAULT — 权重配置统一、策略注册表"),
    ("1.5.1", "2026-05-16", "SHAME — 修复 retreat_search.py 缺少权重参数传递"),
    ("1.5.2", "2026-05-16", "SHAME — 修复 strategy_panel.py 缺少 card_value_weights 参数"),
    ("1.5.3", "2026-05-16", "SHAME — 修复 retreat_search_panel.py 未传递权重"),
    ("1.5.4", "2026-05-16", "SHAME — 删除 ConvertAction 遗留代码"),
    ("1.5.5", "2026-05-16", "SHAME — 删除旧版保底类遗留代码"),
    ("1.5.6", "2026-05-16", "SHAME — 清理 archive/ 和 visualization/ 无用文件"),
    ("1.5.7", "2026-05-16", "DEFAULT — 关于页面完善、版本号系统"),
    ("1.6.0", "2026-05-16", "DEFAULT — GDR 注册表统一（UNIFIED_GDR_REGISTRY）、SuccessChecker 统一成功判断、修复 5 个数值不一致 bug、消除 6 处硬编码、面板下拉列表统一"),
    ("1.7.0", "2026-05-17", "DEFAULT — 流式模拟架构重构：SharedResultCollector 边模拟边提取边丢弃，内存与 N 无关；逐抽真实资源替代线性插值/均摊近似；修复 total_gained 丢失卡片奖励、gdr_dists key 映射、空数据守卫等 9 项 bug；删除死代码 _compact_to_iv_list"),
    ("1.8.0", "2026-05-17", "DEFAULT — 过程分析功能：infer_events 轨迹推断（5种事件类型）、compute_aa/bb/ab/ba 四种交叉统计分析、4种事件模式+3种成败模式、ProcessAnalysisPanel UI 面板（4个Tab）、compact 新增 draw_pity_names/draw_pity_counter_max"),
    ("1.9.0", "2026-05-20", "DEFAULT — 策略代码5阶段重构：CompactResult dataclass 替代裸 dict、SimulationCollector 统一两种模拟模式、StrategyContext + STRATEGY_REGISTRY 统一6种策略、STOP_CONDITION_REGISTRY 统一6种停止条件、策略比较面板、保底概率缓存优化、compact 元数据（策略名/版本号/时间戳）、ssr_ids 消除脆弱匹配"),
]
