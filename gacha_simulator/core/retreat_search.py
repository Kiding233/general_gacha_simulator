from __future__ import annotations
from typing import List, Dict, Optional, Callable, Set
from dataclasses import dataclass, field


@dataclass
class RetreatSearchPoint:
    extra_resource: float
    target_specs: Dict[str, int]
    success_probability: float


@dataclass
class RetreatSearchResult:
    from_pool_id: str
    base_resource: float
    pity_init: Dict[str, int]
    search_mode: str
    points: List[RetreatSearchPoint] = field(default_factory=list)
    resource_only_result: Optional[RetreatSearchResult] = None  # 纯资源搜索结果
    target_only_result: Optional[RetreatSearchResult] = None  # 纯目标卡搜索结果


class RetreatSearchEngine:
    def __init__(
        self,
        config_store,
        from_pool_id: str,
        base_resource: float,
        pity_counter_init: Dict[str, int],
        miss_cost_weights: Optional[Dict[str, float]] = None,
        desire_weights: Optional[Dict[str, float]] = None,
        card_value_weights: Optional[Dict[str, float]] = None,
        success_threshold: float = 0.95,
        gdr_key: str = 'all_targets',
        gdr_threshold: float = 1.0,
        num_simulations: int = 500,
        max_workers: int = 4,
        max_binary_iterations: int = 20,
        precision_draws: int = 1,
        strategy_name: str = 'smart',
        strategy_params: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ):
        self.config_store = config_store
        self.from_pool_id = from_pool_id
        self.base_resource = base_resource
        self.pity_counter_init = pity_counter_init
        self.miss_cost_weights = miss_cost_weights or {}
        self.desire_weights = desire_weights or {}
        self.card_value_weights = card_value_weights or {}
        self.success_threshold = success_threshold
        self.gdr_key = gdr_key
        self.gdr_threshold = gdr_threshold
        self.num_simulations = num_simulations
        self.max_workers = max_workers
        self.max_binary_iterations = max_binary_iterations
        self.precision_draws = precision_draws
        self.strategy_name = strategy_name
        self.strategy_params = strategy_params or {}
        self.progress_callback = progress_callback or (lambda msg, pct: None)
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def _build_truncated_env(self, target_specs, initial_resource_value):
        from .retreat_config import RetreatConfigBuilder
        truncated_store = RetreatConfigBuilder.build(
            original_store=self.config_store,
            from_pool_id=self.from_pool_id,
            initial_resources={'draw_resource': initial_resource_value},
            pity_counter_init=self.pity_counter_init,
        )
        from gacha_simulator.service.batch_simulator import SimulationEnvBuilder
        env = SimulationEnvBuilder.from_config_store(truncated_store)
        return env

    def _simulate_with_resource(self, env, target_specs, resource_value):
        # 如果没有剩余池子，那么没有任务已完成，成功率 100%
        if not env.pools:
            return 1.0
        from gacha_simulator.service.batch_simulator import run_batch_parallel
        from gacha_simulator.core.gdr import compute_success_probability
        ir = dict(env.initial_resources)
        ir['draw_resource'] = resource_value
        histories = run_batch_parallel(
            env=env,
            target_specs=target_specs,
            initial_resources=ir,
            num_simulations=self.num_simulations,
            max_workers=self.max_workers,
            seed=0,
            strategy_name=self.strategy_name,
            strategy_params=self.strategy_params,
        )
        return compute_success_probability(histories, target_specs, self.gdr_key, self.gdr_threshold,
                                           self.desire_weights, self.miss_cost_weights, self.card_value_weights)

    def _extract_cost_per_draw(self, env):
        for p in env.pools:
            cost = p.cost
            if isinstance(cost, list) and cost:
                for opt in cost:
                    if isinstance(opt, dict):
                        return float(list(opt.values())[0])
            elif isinstance(cost, dict):
                return float(list(cost.values())[0])
        return 160

    def search_min_resource(self, target_specs: Dict[str, int],
                            progress_base: int = 0, progress_span: int = 100) -> RetreatSearchResult:
        self._should_stop = False

        def _emit(msg, pct):
            self.progress_callback(msg, progress_base + int(progress_span * pct / 100))

        target_specs = self._filter_obtainable_targets(target_specs)
        if not target_specs:
            _emit("所有目标卡在截断时间线中均不可获取，搜索终止", 100)
            result = RetreatSearchResult(
                from_pool_id=self.from_pool_id,
                base_resource=self.base_resource,
                pity_init=dict(self.pity_counter_init),
                search_mode='resource',
            )
            return result

        result = RetreatSearchResult(
            from_pool_id=self.from_pool_id,
            base_resource=self.base_resource,
            pity_init=dict(self.pity_counter_init),
            search_mode='resource',
        )

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

        _emit("搜索上界...", 5)
        r_hi = 0.0
        prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_hi)

        if prob >= self.success_threshold:
            result.points.append(RetreatSearchPoint(
                extra_resource=0.0,
                target_specs=dict(target_specs),
                success_probability=prob,
            ))
            return result

        r_hi = cost_per_draw * 50
        prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_hi)
        doubling = 0
        while prob < self.success_threshold and doubling < 10:
            if self._should_stop:
                return result
            r_hi *= 2
            prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_hi)
            doubling += 1
            _emit(f"上界搜索: +{r_hi:.0f}, P={prob:.2%}", 10 + doubling * 3)

        r_lo = 0.0
        binary_iter = 0
        while r_hi - r_lo > epsilon and binary_iter < self.max_binary_iterations:
            if self._should_stop:
                return result
            binary_iter += 1
            r_mid = (r_lo + r_hi) / 2.0
            prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_mid)
            if prob >= self.success_threshold:
                r_hi = r_mid
            else:
                r_lo = r_mid
            pct = int(30 + 60 * binary_iter / max(self.max_binary_iterations, 1))
            _emit(f"二分 #{binary_iter}: +{r_mid:.0f}, P={prob:.2%}", min(pct, 95))

        final_prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_hi)
        result.points.append(RetreatSearchPoint(
            extra_resource=r_hi,
            target_specs=dict(target_specs),
            success_probability=final_prob,
        ))
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
        """预过滤：移除截断时间线中不可获取的卡，通过 progress_callback 告知用户"""
        env = self._build_truncated_env(target_specs, self.base_resource)
        obtainable = self._get_obtainable_card_ids(env)

        unobtainable = [cid for cid in target_specs if cid not in obtainable]
        if unobtainable:
            self.progress_callback(
                f"预过滤：以下卡在截断时间线中不可获取，已自动排除: {', '.join(unobtainable)}",
                0
            )

        return {cid: qty for cid, qty in target_specs.items() if cid in obtainable}

    def _get_sorted_card_ids(self, target_specs: Dict[str, int]) -> List[str]:
        weights = {}
        for card_id in target_specs.keys():
            weights[card_id] = self.miss_cost_weights.get(card_id, 1.0)
        return sorted(weights.keys(), key=lambda cid: weights[cid])

    def search_max_targets(self, target_specs: Dict[str, int]) -> RetreatSearchResult:
        self._should_stop = False

        target_specs = self._filter_obtainable_targets(target_specs)
        if not target_specs:
            self.progress_callback("所有目标卡在截断时间线中均不可获取，搜索终止", 100)
            return RetreatSearchResult(
                from_pool_id=self.from_pool_id,
                base_resource=self.base_resource,
                pity_init=dict(self.pity_counter_init),
                search_mode='target',
            )

        result = RetreatSearchResult(
            from_pool_id=self.from_pool_id,
            base_resource=self.base_resource,
            pity_init=dict(self.pity_counter_init),
            search_mode='target',
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
        self._should_stop = False

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

        # 按抽取意愿降序排列
        sorted_ids = sorted(
            candidate_specs.keys(),
            key=lambda cid: self.desire_weights.get(cid, 1.0),
            reverse=True,
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

    def search_pareto(self, target_specs: Dict[str, int]) -> RetreatSearchResult:
        self._should_stop = False

        target_specs = self._filter_obtainable_targets(target_specs)
        if not target_specs:
            self.progress_callback("所有目标卡在截断时间线中均不可获取，搜索终止", 100)
            return RetreatSearchResult(
                from_pool_id=self.from_pool_id,
                base_resource=self.base_resource,
                pity_init=dict(self.pity_counter_init),
                search_mode='pareto',
            )

        result = RetreatSearchResult(
            from_pool_id=self.from_pool_id,
            base_resource=self.base_resource,
            pity_init=dict(self.pity_counter_init),
            search_mode='pareto',
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

        self.progress_callback("Pareto: 搜索完整目标卡的最少资源...", 0)
        res_result = self.search_min_resource(current_specs, progress_base=0, progress_span=15)
        if res_result.points:
            result.points.append(res_result.points[-1])
        self._should_stop = False

        for i, cid in enumerate(card_ids):
            if self._should_stop:
                break
            reduced_specs = dict(current_specs)
            del reduced_specs[cid]
            if not reduced_specs:
                break

            base = 15 + i * 85 // len(card_ids)
            span = max(1, 85 // len(card_ids))
            self.progress_callback(f"Pareto: 移除 {cid}, 搜索剩余 {len(reduced_specs)} 卡的最少资源...", base)
            res_result = self.search_min_resource(reduced_specs, progress_base=base, progress_span=span)
            if res_result.points:
                result.points.append(res_result.points[-1])
            self._should_stop = False

            current_specs = reduced_specs

        self.progress_callback("Pareto搜索完成", 100)
        return result
