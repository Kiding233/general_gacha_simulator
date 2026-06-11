from __future__ import annotations
import zlib
from typing import List, Dict, Optional, Callable, Set
from dataclasses import dataclass, field

from .forward_backward import ResourceSearchStep


@dataclass
class RetreatSearchPoint:
    extra_resource: float
    target_specs: Dict[str, int]
    success_probability: float


@dataclass
class PlanSearchResult:
    """统一方案搜索结果——兼容旧 RetreatSearchResult 的全部字段。"""
    search_mode: str  # 'min_resource' | 'forward' | 'backward' | 'pareto'
    direction: str = 'backward'  # 仅 Pareto 模式使用：'forward' | 'backward'
    # 向后兼容字段（旧 RetreatSearchResult）
    from_pool_id: Optional[str] = None  # None = 完整时间线模式
    base_resource: float = 0.0
    pity_init: Dict[str, int] = field(default_factory=dict)
    points: List[RetreatSearchPoint] = field(default_factory=list)
    resource_only_result: Optional[PlanSearchResult] = None   # type: ignore
    target_only_result: Optional[PlanSearchResult] = None     # type: ignore

    # 新增字段
    start_mode: str = 'full_timeline'  # 'full_timeline' | 'from_retreat'
    success: bool = True

    # 最少资源
    min_resource: Optional[float] = None
    binary_steps: List = field(default_factory=list)  # ResourceSearchStep 列表

    # 最多目标卡
    forward_result: Optional[any] = None   # type: ignore  # ForwardResult
    backward_result: Optional[any] = None  # type: ignore  # BackwardResult

    # 元数据
    cost_per_draw: float = 160.0
    target_specs: Dict[str, int] = field(default_factory=dict)
    total_iterations: int = 0
    final_success_probability: float = 0.0

    def __post_init__(self):
        # 推断 start_mode
        if not self.start_mode or self.start_mode == 'full_timeline':
            self.start_mode = 'full_timeline' if self.from_pool_id is None else 'from_retreat'
        # 最少资源结果自动填充兼容字段
        if self.min_resource is not None and not self.points:
            self.points = [RetreatSearchPoint(
                extra_resource=self.min_resource - self.base_resource,
                target_specs=dict(self.target_specs),
                success_probability=self.final_success_probability,
            )]


# 向后兼容别名
RetreatSearchResult = PlanSearchResult


class PlanSearchEngine:
    """统一方案搜索引擎——支持完整时间线与截断时间线（退路点）两种模式。

    from_pool_id=None  → 完整时间线，使用 SimulationEnvBuilder.from_config_store()
    from_pool_id=str   → 截断时间线，使用 RetreatConfigBuilder.build()
    """

    def __init__(
        self,
        config_store,
        from_pool_id: Optional[str] = None,
        base_resource: float = 0.0,
        pity_counter_init: Optional[Dict[str, int]] = None,
        add_order: Optional[Dict[str, float]] = None,
        remove_order: Optional[Dict[str, float]] = None,
        success_threshold: float = 0.95,
        gdr_key: str = 'all_targets',
        gdr_threshold: float = 1.0,
        num_simulations: int = 500,
        max_workers: int = 4,
        max_binary_iterations: int = 20,
        precision_draws: int = 1,
        strategy_name: str = 'smart',
        strategy_params: Optional[Dict] = None,
        upper_bound: float = 8000.0,
        lower_bound: float = 0.0,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ):
        self.config_store = config_store
        self.from_pool_id = from_pool_id
        self.base_resource = base_resource
        self.pity_counter_init = pity_counter_init or {}
        self.add_order = add_order or {}          # 搜索排序用——加入顺序（来自方案搜索面板）
        self.remove_order = remove_order or {}    # 搜索排序用——删除顺序（来自方案搜索面板）
        self.success_threshold = success_threshold
        self.gdr_key = gdr_key
        self.gdr_threshold = gdr_threshold
        self.num_simulations = num_simulations
        self.max_workers = max_workers
        self.max_binary_iterations = max_binary_iterations
        self.precision_draws = precision_draws
        self.strategy_name = strategy_name
        self.strategy_params = strategy_params or {}
        self.upper_bound = upper_bound
        self.lower_bound = lower_bound
        self.progress_callback = progress_callback or (lambda msg, pct: None)
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def _build_env(self, target_specs, initial_resource_value):
        """构建模拟环境——根据 from_pool_id 分叉：
        - None: 完整时间线（SimulationEnvBuilder）
        - str:  截断时间线（RetreatConfigBuilder）
        """
        if self.from_pool_id is None:
            # 完整时间线模式
            from gacha_simulator.service.batch_simulator import SimulationEnvBuilder
            env = SimulationEnvBuilder.from_config_store(self.config_store)
            ir = dict(env.initial_resources)
            ir['draw_resource'] = initial_resource_value
            env.initial_resources = ir
            return env
        else:
            # 截断时间线模式（退路点）
            from .retreat_config import RetreatConfigBuilder
            truncated_store = RetreatConfigBuilder.build(
                original_store=self.config_store,
                from_pool_id=self.from_pool_id,
                initial_resources={'draw_resource': initial_resource_value},
                pity_counter_init=self.pity_counter_init,
            )
            from gacha_simulator.service.batch_simulator import SimulationEnvBuilder
            return SimulationEnvBuilder.from_config_store(truncated_store)

    # 保留旧方法名作为别名，向后兼容
    _build_truncated_env = _build_env

    # ── GDR 兼容性检查 ──────────────────────────────────────────────────

    def _check_gdr_compatibility(self, result, _emit):
        """检查 GDR 与「最少资源」搜索模式的兼容性（Q8）。

        读取 GDR 注册表中的 compatible_with_min_resource 字段（A4），
        结合运行时阈值配置，进行三类兼容性检查：
        - Type 1：lower_is_better / 不兼容 GDR → 直接拒绝
        - Type 2：默认阈值退化（threshold ≤ 0.0）→ 警告
        - Type 3：零资源未定义（除零）→ 提示

        Returns:
            True 如果兼容（可以继续搜索），False 如果已设置 result 失败原因。
        """
        from gacha_simulator.core.gdr import resolve_gdr_definition
        gdr_def = resolve_gdr_definition(self.gdr_key)

        if gdr_def and not gdr_def.compatible_with_min_resource:
            result.success = False
            reason = (
                "搜索方向相反（lower_is_better）"
                if gdr_def.lower_is_better
                else "p(r) 在合理资源范围内恒为常数，搜索无法收敛"
            )
            _emit(f"错误：GDR「{gdr_def.display_name}」与「最少资源」搜索不兼容——{reason}。"
                  f"请切换到连续型 GDR（如「简单目标达成率」）。", 100)
            return False

        # 第二类：默认阈值退化警告（仅当用户使用默认阈值 0.0 时）
        _DEGENERATE_DEFAULTS = {'resource_remaining': 0.0, 'pity_draws': 0.0}
        if self.gdr_key in _DEGENERATE_DEFAULTS and self.gdr_threshold <= _DEGENERATE_DEFAULTS[self.gdr_key]:
            _emit(f"⚠ GDR「{gdr_def.display_name}」的当前阈值 ({self.gdr_threshold}) "
                  f"可能使所有资源水平都满足条件。建议设置有意义的阈值。", 10)

        # 第三类：零资源未定义行为提示
        _ZERO_UNDEFINED = {'resource_efficiency', 'draw_conversion_efficiency'}
        if self.gdr_key in _ZERO_UNDEFINED:
            _emit(f"注意：GDR「{gdr_def.display_name}」在零资源时未定义（除零），"
                  f"搜索结果在极低资源区间可能不可靠。", 10)

        return True

    def _simulate_with_resource(self, env, target_specs, resource_value):
        # 如果没有剩余池子，那么没有任务已完成，成功率 100%
        if not env.pools:
            return 1.0
        from gacha_simulator.service.batch_simulator import run_batch_parallel
        from gacha_simulator.core.gdr import make_gdr_calculator
        ir = dict(env.initial_resources)
        ir['draw_resource'] = resource_value
        histories = run_batch_parallel(
            env=env,
            target_specs=target_specs,
            initial_resources=ir,
            num_simulations=self.num_simulations,
            max_workers=self.max_workers,
            seed=zlib.crc32(str(resource_value).encode()) % (2**31),
            strategy_name=self.strategy_name,
            strategy_params=self.strategy_params,
        )
        checker = make_gdr_calculator(
            self.config_store, target_specs, self.gdr_key,
            gdr_threshold=self.gdr_threshold,
        )
        _, _, prob = checker.check_batch(histories)
        return prob

    def _extract_cost_per_draw(self, env):
        """[DEPRECATED] 请使用模块级 get_cost_per_draw(env.pools)"""
        return get_cost_per_draw(env.pools)

    def _find_upper_bound(self, env, target_specs, cost_per_draw, max_iter=15):
        """翻倍搜索上界——确保 r_hi 满足 P(success | r_hi) ≥ θ。

        Returns:
            (r_hi, prob, total_iterations, steps): 成功找到上界时 prob ≥ θ；
            耗尽翻倍次数仍未找到时 prob < θ，由调用方处理失败。
        """
        r_hi = max(self.upper_bound, cost_per_draw)
        iteration = 1
        prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_hi)
        steps = [ResourceSearchStep(
            iteration=iteration, resource_value=r_hi,
            success_probability=prob, phase='搜索上界',
            lo_bound=self.lower_bound, hi_bound=r_hi,
        )]
        doubling = 0
        self.progress_callback(
            f"上界搜索: +{r_hi:.0f}, P={prob:.2%} → 区间[{self.lower_bound:.0f}, {r_hi:.0f}]",
            10 + doubling * 3,
        )
        while prob < self.success_threshold and doubling < max_iter:
            if self._should_stop:
                return r_hi, prob, iteration, steps
            r_hi *= 2
            iteration += 1
            prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_hi)
            steps.append(ResourceSearchStep(
                iteration=iteration, resource_value=r_hi,
                success_probability=prob, phase='搜索上界',
                lo_bound=self.lower_bound, hi_bound=r_hi,
            ))
            doubling += 1
            self.progress_callback(
                f"上界搜索: +{r_hi:.0f}, P={prob:.2%} → 区间[{self.lower_bound:.0f}, {r_hi:.0f}]",
                10 + doubling * 3,
            )
        return r_hi, prob, iteration, steps

    def search_min_resource(self, target_specs: Dict[str, int],
                            progress_base: int = 0, progress_span: int = 100) -> RetreatSearchResult:
        """二分搜索最少资源——找到使 P(success | r) ≥ θ 的最小额外资源 r。

        在 [r_lo, r_hi] 区间上执行噪声二分搜索，每步运行 num_simulations 次
        蒙特卡洛模拟估计 P(success | r_mid)，根据 prob ≥ success_threshold 决定
        二分方向。收敛条件：r_hi − r_lo ≤ epsilon。

        GDR 兼容性说明：
        - lower_is_better GDR（如 resource_consumed）与「最少资源」语义不兼容——
          此类 GDR 在入口处直接拒绝。
        - 对于二值 GDR（如 all_targets），当 p(r) 为平滑函数（非阶跃）时，可能在
          高资源区间出现辨别力退化——p ≈ 1.0 时二分搜索失去方向。当前默认配置的
          p(r) 为阶跃函数（[事实一]），不存在此问题。若未来引入平滑 p(r) 的 GDR，
          建议切换到连续型 GDR（如 target_achievement）以获得更精确的资源估计。
        """
        # 不在此处重置 _should_stop——由 Worker 在启动搜索前通过 __init__ 保证初始状态。
        # 若调用方（如 search_pareto）连续多次调用本方法，_should_stop 由用户操作驱动。

        def _emit(msg, pct):
            self.progress_callback(msg, progress_base + int(progress_span * pct / 100))

        target_specs = self._filter_obtainable_targets(target_specs)
        iteration = 0

        if not target_specs:
            _emit("所有目标卡在截断时间线中均不可获取，搜索终止", 100)
            result = RetreatSearchResult(
                from_pool_id=self.from_pool_id,
                base_resource=self.base_resource,
                pity_init=dict(self.pity_counter_init),
                search_mode='min_resource',
            )
            return result

        result = RetreatSearchResult(
            from_pool_id=self.from_pool_id,
            base_resource=self.base_resource,
            pity_init=dict(self.pity_counter_init),
            search_mode='min_resource',
        )

        # 1.7：GDR 兼容性检查（替代原 §1.6 独立 lower_is_better 守卫）
        if not self._check_gdr_compatibility(result, _emit):
            return result

        env = self._build_truncated_env(target_specs, self.base_resource)

        # 没有后续池子的情况，直接返回成功
        if not env.pools:
            result.points.append(RetreatSearchPoint(
                extra_resource=0.0,
                target_specs=dict(target_specs),
                success_probability=1.0,
            ))
            _emit("没有后续池子，已成功", 100)
            return result

        cost_per_draw = self._extract_cost_per_draw(env)
        epsilon = cost_per_draw * self.precision_draws

        # 基线检测：仅当下界=0 时测试零额外资源是否已达标（避免不必要的点）
        if self.lower_bound <= 0:
            _emit("基线检测...", 5)
            r_hi = 0.0
            iteration += 1
            prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_hi)
            result.binary_steps.append(ResourceSearchStep(
                iteration=iteration, resource_value=r_hi,
                success_probability=prob, phase='基线检测',
                lo_bound=self.lower_bound, hi_bound=r_hi,
            ))

            if prob >= self.success_threshold:
                result.points.append(RetreatSearchPoint(
                    extra_resource=0.0,
                    target_specs=dict(target_specs),
                    success_probability=prob,
                ))
                result.min_resource = self.base_resource + r_hi
                result.final_success_probability = prob
                result.total_iterations = iteration
                result.cost_per_draw = cost_per_draw
                result.target_specs = dict(target_specs)
                return result

        _emit("搜索上界...", 5)
        r_hi, prob, ub_iters, ub_steps = self._find_upper_bound(
            env, target_specs, cost_per_draw, max_iter=15,
        )
        iteration += ub_iters
        result.binary_steps.extend(ub_steps)

        if prob < self.success_threshold:
            result.success = False
            _emit(f"错误：15 次翻倍后仍未找到上界——当前上界 {r_hi:.0f} 资源不足，"
                  f"请增大起始上界或确认配置可达。", 100)
            return result

        r_lo = self.lower_bound
        binary_iter = 0
        while r_hi - r_lo > epsilon and binary_iter < self.max_binary_iterations:
            if self._should_stop:
                return result
            binary_iter += 1
            r_mid = (r_lo + r_hi) / 2.0
            iteration += 1
            prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_mid)
            if prob >= self.success_threshold:
                phase = '二分(满足)'
                r_hi = r_mid
            else:
                phase = '二分(不足)'
                r_lo = r_mid
            result.binary_steps.append(ResourceSearchStep(
                iteration=iteration, resource_value=r_mid,
                success_probability=prob, phase=phase,
                lo_bound=r_lo, hi_bound=r_hi,
            ))
            pct = int(30 + 60 * binary_iter / max(self.max_binary_iterations, 1))
            _emit(f"二分 #{binary_iter}: R={r_mid:.0f} P={prob:.2%} → [{r_lo:.0f}, {r_hi:.0f}]", min(pct, 95))

        iteration += 1
        final_prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_hi)
        result.binary_steps.append(ResourceSearchStep(
            iteration=iteration, resource_value=r_hi,
            success_probability=final_prob, phase='最终验证',
            lo_bound=r_lo, hi_bound=r_hi,
        ))
        result.points.append(RetreatSearchPoint(
            extra_resource=r_hi,
            target_specs=dict(target_specs),
            success_probability=final_prob,
        ))
        result.success = final_prob >= self.success_threshold
        result.min_resource = self.base_resource + r_hi
        result.final_success_probability = final_prob
        result.total_iterations = iteration
        result.cost_per_draw = cost_per_draw
        result.target_specs = dict(target_specs)
        _emit(f"最少额外资源: +{r_hi:.0f}, P={final_prob:.2%}", 100)
        return result

    def _get_obtainable_card_ids(self, env) -> Set[str]:
        """从截断后的环境中收集所有可获取的卡ID"""
        obtainable = set()
        for pool in env.pools:
            if pool.is_exchange:
                if pool.exchange_card_id:
                    obtainable.add(pool.exchange_card_id)
            else:
                for reward, _ in pool.rewards:
                    obtainable.add(reward.id)
        return obtainable

    def _filter_obtainable_targets(self, target_specs: Dict[str, int]) -> Dict[str, int]:
        """预过滤：移除不可获取的卡。

        完整时间线模式（from_pool_id=None）：所有卡均可获取，不做过滤。
        截断时间线模式：只保留截断后池子中实际可获取的卡。
        """
        # 完整时间线模式：所有卡均可获取
        if self.from_pool_id is None:
            return dict(target_specs)

        env = self._build_env(target_specs, self.base_resource)
        obtainable = self._get_obtainable_card_ids(env)

        unobtainable = [cid for cid in target_specs if cid not in obtainable]
        if unobtainable:
            self.progress_callback(
                f"预过滤：以下卡在截断时间线中不可获取，已自动排除: {', '.join(unobtainable)}",
                0
            )

        return {cid: qty for cid, qty in target_specs.items() if cid in obtainable}

    def _get_sorted_card_ids(self, target_specs: Dict[str, int]) -> List[str]:
        """按删除顺序升序排列——低优先级的卡优先移除。"""
        return sorted(
            target_specs.keys(),
            key=lambda cid: self.remove_order.get(cid, 1.0)
        )

    def search_max_targets(self, target_specs: Dict[str, int]) -> RetreatSearchResult:
        # 不在此处重置 _should_stop——由 Worker 在启动搜索前通过 __init__ 保证初始状态

        target_specs = self._filter_obtainable_targets(target_specs)
        if not target_specs:
            self.progress_callback("所有目标卡在截断时间线中均不可获取，搜索终止", 100)
            return RetreatSearchResult(
                from_pool_id=self.from_pool_id,
                base_resource=self.base_resource,
                pity_init=dict(self.pity_counter_init),
                search_mode='backward',
            )

        result = RetreatSearchResult(
            from_pool_id=self.from_pool_id,
            base_resource=self.base_resource,
            pity_init=dict(self.pity_counter_init),
            search_mode='backward',
        )

        env = self._build_truncated_env(target_specs, self.base_resource)

        # 没有后续池子的情况，直接返回成功
        if not env.pools:
            result.points.append(RetreatSearchPoint(
                extra_resource=0.0,
                target_specs=dict(target_specs),
                success_probability=1.0,
            ))
            self.progress_callback("没有后续池子，已成功", 100)
            return result
        
        current_specs = dict(target_specs)
        card_ids = self._get_sorted_card_ids(target_specs)

        prob = self._simulate_with_resource(env, current_specs, self.base_resource)
        result.points.append(RetreatSearchPoint(
            extra_resource=0.0,
            target_specs=dict(current_specs),
            success_probability=prob,
        ))

        if prob >= self.success_threshold:
            return result

        for i, cid in enumerate(card_ids):
            if self._should_stop:
                break
            reduced_specs = dict(current_specs)
            del reduced_specs[cid]
            if not reduced_specs:
                break

            env = self._build_truncated_env(reduced_specs, self.base_resource)
            prob = self._simulate_with_resource(env, reduced_specs, self.base_resource)
            current_specs = reduced_specs
            result.points.append(RetreatSearchPoint(
                extra_resource=0.0,
                target_specs=dict(current_specs),
                success_probability=prob,
            ))
            pct = int((i + 1) / len(card_ids) * 100)
            self.progress_callback(f"后退法: 移除 {cid}, 剩余 {len(current_specs)} 卡, P={prob:.2%}", pct)

            if prob >= self.success_threshold:
                break

        return result

    def search_max_targets_forward(self, candidate_specs: Dict[str, int]) -> RetreatSearchResult:
        """前进法：从空目标集开始，按抽取意愿降序逐个添加，直到成功率跌破阈值回退一步。

        Args:
            candidate_specs: 候选卡及其目标数量 {card_id: qty}，全部可获取时纳入
        Returns:
            RetreatSearchResult，其中 points 按添加顺序排列，最后一个是最终有效方案
        """

        candidate_specs = self._filter_obtainable_targets(candidate_specs)
        if not candidate_specs:
            self.progress_callback("所有候选卡在截断时间线中均不可获取，搜索终止", 100)
            return RetreatSearchResult(
                from_pool_id=self.from_pool_id,
                base_resource=self.base_resource,
                pity_init=dict(self.pity_counter_init),
                search_mode='forward',
            )

        result = RetreatSearchResult(
            from_pool_id=self.from_pool_id,
            base_resource=self.base_resource,
            pity_init=dict(self.pity_counter_init),
            search_mode='forward',
        )

        env = self._build_truncated_env(candidate_specs, self.base_resource)

        # 没有后续池子的情况，直接返回成功（所有候选卡均可获得）
        if not env.pools:
            result.points.append(RetreatSearchPoint(
                extra_resource=0.0,
                target_specs=dict(candidate_specs),
                success_probability=1.0,
            ))
            self.progress_callback("没有后续池子，已成功", 100)
            return result

        # 按加入顺序升序排列——从小到大依次添加
        sorted_ids = sorted(
            candidate_specs.keys(),
            key=lambda cid: self.add_order.get(cid, 1.0),
        )

        current_specs: Dict[str, int] = {}
        last_valid_specs: Dict[str, int] = {}
        last_valid_prob = 1.0

        total_steps = len(sorted_ids)
        for i, card_id in enumerate(sorted_ids):
            if self._should_stop:
                break

            pct = int((i / max(total_steps, 1)) * 95) + 5
            self.progress_callback(f"前进法: 尝试添加 {card_id}", pct)

            current_specs[card_id] = candidate_specs[card_id]
            env = self._build_truncated_env(current_specs, self.base_resource)
            prob = self._simulate_with_resource(env, current_specs, self.base_resource)

            result.points.append(RetreatSearchPoint(
                extra_resource=0.0,
                target_specs=dict(current_specs),
                success_probability=prob,
            ))

            if prob >= self.success_threshold:
                last_valid_specs = dict(current_specs)
                last_valid_prob = prob
            else:
                # 回退到上一个有效状态；如果第一步就失败，使用仅含第一张卡的方案
                if not last_valid_specs:
                    last_valid_specs = {card_id: candidate_specs[card_id]}
                    last_valid_prob = prob
                    result.success = False
                self.progress_callback(
                    f"前进法完成: 添加 {card_id} 跌破阈值 (P={prob:.2%}), "
                    f"回退到 {len(last_valid_specs)} 卡, P={last_valid_prob:.2%}",
                    100,
                )
                break

        # 如果所有候选卡都添加成功
        if not self._should_stop and len(current_specs) == len(sorted_ids):
            last_valid_specs = dict(current_specs)
            last_valid_prob = result.points[-1].success_probability if result.points else 1.0
            self.progress_callback(
                f"前进法完成: 全部 {len(last_valid_specs)} 张候选卡均已添加, P={last_valid_prob:.2%}",
                100,
            )

        return result

    def search_pareto(self, target_specs: Dict[str, int], direction: str = 'backward') -> RetreatSearchResult:
        """Pareto 前沿搜索。

        direction='backward': 从完整目标集开始，逐个移除低价值卡片（当前行为）。
        direction='forward':  从最有价值单卡开始，逐个添加次优卡片。
        两种方向产生相同的 Pareto 前沿点集，仅迭代顺序与进度信息不同。
        """
        # 不在此处重置 _should_stop——由 Worker 在启动搜索前通过 __init__ 保证初始状态

        target_specs = self._filter_obtainable_targets(target_specs)
        if not target_specs:
            self.progress_callback("所有目标卡在截断时间线中均不可获取，搜索终止", 100)
            return RetreatSearchResult(
                from_pool_id=self.from_pool_id,
                base_resource=self.base_resource,
                pity_init=dict(self.pity_counter_init),
                search_mode='pareto',
                direction=direction,
            )

        result = RetreatSearchResult(
            from_pool_id=self.from_pool_id,
            base_resource=self.base_resource,
            pity_init=dict(self.pity_counter_init),
            search_mode='pareto',
            direction=direction,
        )

        env = self._build_truncated_env(target_specs, self.base_resource)

        # 没有后续池子的情况，直接返回成功
        if not env.pools:
            result.points.append(RetreatSearchPoint(
                extra_resource=0.0,
                target_specs=dict(target_specs),
                success_probability=1.0,
            ))
            self.progress_callback("没有后续池子，已成功", 100)
            return result

        if direction == 'forward':
            # 前进法：按加入顺序升序排列——从小到大依次添加
            card_ids = sorted(
                target_specs.keys(),
                key=lambda cid: self.add_order.get(cid, 1.0),
            )

            first_id = card_ids[0]
            current_specs = {first_id: target_specs[first_id]}

            self.progress_callback(f"Pareto前进: 搜索 {first_id} 的最少资源...", 0)
            res_result = self.search_min_resource(current_specs, progress_base=0, progress_span=15)
            if res_result.points:
                result.points.append(res_result.points[-1])

            for i, cid in enumerate(card_ids[1:], start=1):
                if self._should_stop:
                    break
                current_specs[cid] = target_specs[cid]  # 添加一张卡

                base = 15 + i * 85 // len(card_ids)
                span = max(1, 85 // len(card_ids))
                self.progress_callback(
                    f"Pareto前进: 添加 {cid}, 搜索 {len(current_specs)} 卡的最少资源...", base,
                )
                res_result = self.search_min_resource(current_specs, progress_base=base, progress_span=span)
                if res_result.points:
                    result.points.append(res_result.points[-1])
        else:
            # 后退法：从完整目标集开始，逐个移除
            current_specs = dict(target_specs)
            card_ids = self._get_sorted_card_ids(target_specs)  # 低删除顺序值优先移除

            self.progress_callback("Pareto后退: 搜索完整目标卡的最少资源...", 0)
            res_result = self.search_min_resource(current_specs, progress_base=0, progress_span=15)
            if res_result.points:
                result.points.append(res_result.points[-1])

            for i, cid in enumerate(card_ids):
                if self._should_stop:
                    break
                reduced_specs = dict(current_specs)
                del reduced_specs[cid]
                if not reduced_specs:
                    break

                base = 15 + i * 85 // len(card_ids)
                span = max(1, 85 // len(card_ids))
                self.progress_callback(
                    f"Pareto后退: 移除 {cid}, 搜索剩余 {len(reduced_specs)} 卡的最少资源...", base,
                )
                res_result = self.search_min_resource(reduced_specs, progress_base=base, progress_span=span)
                if res_result.points:
                    result.points.append(res_result.points[-1])

                current_specs = reduced_specs

        self.progress_callback("Pareto搜索完成", 100)
        return result


# 向后兼容别名——旧代码可继续使用 RetreatSearchEngine
RetreatSearchEngine = PlanSearchEngine


# ═══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════════

def get_cost_per_draw(pools) -> float:
    """从池列表中提取单抽资源成本（取首个有效值）。

    注意：多池成本不同时不存在正确值——此函数仅返回近似值。
    二分搜索在资源空间运行，cost 不影响搜索正确性。
    """
    if not pools:
        return 160
    for p in pools:
        cost = getattr(p, 'cost', None)
        if cost is None:
            continue
        if isinstance(cost, (int, float)) and cost > 0:
            return float(cost)
        if isinstance(cost, list) and cost:
            for opt in cost:
                if isinstance(opt, dict):
                    return float(list(opt.values())[0])
        elif isinstance(cost, dict):
            return float(list(cost.values())[0])
    return 160


def extract_cost_per_draw_by_resource(pool_entries) -> dict:
    """从池配置解析每种资源类型的每抽成本 {resource_id: cost}。

    遍历所有池的 cost 字段（格式 'draw_resource:160|exchange_currency:5'），
    按 resource_id 分类收集。同资源类型多池冲突取首个 + logging.warning（每 rid 仅警告一次）。
    默认回退 {'draw_resource': 160.0}。

    供面板层调用，接受 ConfigStore 条目列表，返回 dict。
    """
    import logging
    _logger = logging.getLogger(__name__)
    # 模块级去重：同一资源类型的多池冲突只警告一次
    if '_cost_warned' not in extract_cost_per_draw_by_resource.__dict__:
        extract_cost_per_draw_by_resource._cost_warned = set()
    _cost_warned = extract_cost_per_draw_by_resource._cost_warned
    costs: dict = {}
    for pe in pool_entries:
        cost_str = getattr(pe, 'cost', '')
        if not cost_str:
            continue
        for part in cost_str.split('|'):
            part = part.strip()
            if ':' not in part:
                continue
            rid, _, val_str = part.partition(':')
            rid = rid.strip()
            if rid not in costs:
                try:
                    costs[rid] = float(val_str.strip())
                except ValueError:
                    pass
            elif rid not in _cost_warned:
                _logger.warning(
                    f"资源类型 '{rid}' 在多个池中有不同成本值，使用第一个: {costs[rid]}"
                )
                _cost_warned.add(rid)
    if not costs:
        costs['draw_resource'] = 160.0
    return costs
