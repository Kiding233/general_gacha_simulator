from .result_types import CompactResult
from .collector import SimulationCollector, InfoVectorCollector, CompactCollector
from .pool import Pool, Reward, CostOption, PoolCost, parse_cost_string, cost_to_string, compute_bonus_resources
from .action import Action, DrawAction, WaitAction
from .state import GachaState
from .info_vector import InfoVector
from .pity import (
    PityBehavior, SoftPityBehavior, HardPityBehavior,
    PityDefParsed, PoolPitySpec,
    PityState, PityEngine,
    parse_pity_file, build_pity_engine,
)
from .strategy import (
    Strategy, StrategyContext,
    SmartStrategy, PoolQuotaStrategy, PityReserveStrategy, StopOnTargetStrategy,
    FixedCountStrategy, TargetHuntingStrategy, CompositeStrategy,
    STRATEGY_REGISTRY, create_strategy, strategy_type_to_key, strategy_key_to_type,
)
from .stop_condition import (
    StopCondition, FixedActionCountCondition, ResourceThresholdCondition,
    TargetAcquiredCondition, TimeLimitCondition, CompositeStopCondition,
    AllPoolsEndCondition, LastDrawCardCondition,
    STOP_CONDITION_REGISTRY, create_stop_condition,
    stop_condition_type_to_key, stop_condition_key_to_type,
)
from .resource_gain import ResourceGainFunction, LinearResourceGain, PeriodicResourceGain, StepResourceGain, CompositeResourceGain, ScheduleResourceGain, expand_gain_rules_to_schedule
from .generalized_drop_rate import (
    GeneralizedDropRate, RarityValueAtT, CumulativeResourceEfficiency, PityProgressAtT,
    DropRateBetweenT1T2, TotalValueAtT, TargetCardCountAtT, TargetCardPercentageAtT, TargetCardEfficiencyAtT
)
from .schedule import PoolSchedule, PoolScheduleManager
from .target_card import TargetCard, TargetCardSet
from .gdr_analysis import (
    SuccessProbabilityAnalyzer, LegacyGDRCalculator,
    compute_gdr_count, compute_gdr_percentage, compute_gdr_efficiency
)
from .pool_config import PoolConfig, CardDef, CardCatalog, parse_schedule_file, parse_distribution_file, parse_cards_file, load_config_from_directory
from .distribution import EmpiricalDistribution, DistributionSummary, JointSamples, WorstCaseAnalysis, BestCaseAnalysis
from .risk_analysis import RiskAnalyzer
from .gdr import GDRContext, GDR_REGISTRY, COMPACT_GDR_REGISTRY, UNIFIED_GDR_REGISTRY, register_gdr, GDRCalculator, make_gdr_calculator, GDRDefinition, populate_gdr_combo, get_default_threshold, compute_gdr_from_compact, compute_gdr_from_cumulative, compute_success_probability, parse_gdr_key, get_expanded_gdr_entries, resolve_gdr_definition, is_resource_gdr
from .per_pool_analysis import (
    PoolSnapshot, CumulativeSnapshot,
    compute_per_pool_snapshots, compute_cumulative_snapshots,
    compute_per_pool_snapshots_batch, compute_cumulative_snapshots_batch,
    per_pool_summary_stats, cumulative_gdr_at_pool_ends,
    TransitionMatrix, compute_transition_matrices,
    compute_transition_matrices_from_flags, compute_transition_flags_from_gdr,
)
from .forward_backward import (
    ForwardStep, BackwardStep, ForwardResult, BackwardResult,
)
from .vulnerability import (
    VulnerabilityInterval, PityStatSnapshot, PoolVulnerabilityResult, VulnerabilityAnalysisResult,
    compute_vulnerability_analysis, plot_vulnerability, plot_vulnerability_ridge,
)
from .worst_impact import (
    WorstImpactAnalyzer, WorstImpactResult, ConditionalResourceDistribution,
    DrawTargetStrategy,
)
from .result_store import (
    ResultStore, StoredDataset, ComparabilityFingerprint, ComparabilityDiff, compute_config_hash,
)
from .gdr_binning import (
    BinningResult, compute_bins, detect_step_size, compute_aligned_bins,
)
from .comparison_analyzer import (
    DescriptiveStats, HypothesisTestResult, ParetoFrontier,
    dd_bootstrap_test, compute_dominance_matrix, compute_pvalue_matrix,
    compute_gdr_values_for_datasets, holm_bonferroni, benjamini_hochberg,
)
# BootstrapEngine / BootstrapResult 改为惰性导入（__getattr__），
# 避免顶层 import 时级联加载 scipy.stats。Windows spawn 下 worker
# 进程 import gacha_simulator.core 若同时加载 scipy 大 DLL 可触发
# 页面文件耗尽 (ImportError: DLL load failed)。
from .streaming import StreamingAnalyzer, StreamingSuccessCounter, SharedResultCollector, DrawSequenceExtractor, extract_aggregate, extract_process, WorkerLocalExtractor, merge_extraction_packets
from .process_trace import PoolEvent, SampleTrace, infer_events, compute_pool_gdr_cumulative, compute_pool_gdr_single_pool
from .process_analysis import (
    compute_aa, compute_bb, compute_ab, compute_ba,
    to_event_type_sequence, to_event_type_set, to_custom_pattern, to_raw_trajectory,
    to_success_sequence, to_success_set, to_success_count, to_success_custom,
    EVENT_MODE_MAP, SUCCESS_MODE_MAP,
)

__all__ = [
    'CompactResult',
    'SimulationCollector', 'InfoVectorCollector', 'CompactCollector',
    'Pool', 'Reward', 'CostOption', 'PoolCost', 'parse_cost_string', 'cost_to_string', 'compute_bonus_resources',
    'Action', 'DrawAction', 'WaitAction',
    'GachaState',
    'InfoVector',
    'PityBehavior', 'SoftPityBehavior', 'HardPityBehavior',
    'PityDefParsed', 'PoolPitySpec',
    'PityState', 'PityEngine',
    'parse_pity_file', 'build_pity_engine',
    'Strategy', 'StrategyContext',
    'SmartStrategy', 'PoolQuotaStrategy', 'PityReserveStrategy', 'StopOnTargetStrategy',
    'FixedCountStrategy', 'TargetHuntingStrategy', 'CompositeStrategy',
    'STRATEGY_REGISTRY', 'create_strategy', 'strategy_type_to_key', 'strategy_key_to_type',
    'StopCondition', 'FixedActionCountCondition', 'ResourceThresholdCondition',
    'TargetAcquiredCondition', 'TimeLimitCondition', 'CompositeStopCondition',
    'AllPoolsEndCondition', 'LastDrawCardCondition',
    'STOP_CONDITION_REGISTRY', 'create_stop_condition',
    'stop_condition_type_to_key', 'stop_condition_key_to_type',
    'ResourceGainFunction', 'LinearResourceGain', 'PeriodicResourceGain', 'StepResourceGain', 'CompositeResourceGain', 'ScheduleResourceGain', 'expand_gain_rules_to_schedule',
    'GeneralizedDropRate', 'RarityValueAtT', 'CumulativeResourceEfficiency', 'PityProgressAtT',
    'DropRateBetweenT1T2', 'TotalValueAtT', 'TargetCardCountAtT', 'TargetCardPercentageAtT', 'TargetCardEfficiencyAtT',
    'PoolSchedule', 'PoolScheduleManager',
    'TargetCard', 'TargetCardSet',
    'SuccessProbabilityAnalyzer', 'LegacyGDRCalculator',
    'compute_gdr_count', 'compute_gdr_percentage', 'compute_gdr_efficiency',
    'PoolConfig', 'CardDef', 'CardCatalog', 'parse_schedule_file', 'parse_distribution_file', 'parse_cards_file', 'load_config_from_directory',
    'EmpiricalDistribution', 'DistributionSummary', 'JointSamples', 'WorstCaseAnalysis', 'BestCaseAnalysis',
    'RiskAnalyzer',
    'GDRContext', 'GDR_REGISTRY', 'COMPACT_GDR_REGISTRY', 'UNIFIED_GDR_REGISTRY', 'register_gdr', 'GDRCalculator', 'make_gdr_calculator', 'GDRDefinition', 'populate_gdr_combo', 'get_default_threshold', 'compute_gdr_from_compact', 'compute_gdr_from_cumulative', 'compute_success_probability', 'parse_gdr_key', 'get_expanded_gdr_entries', 'resolve_gdr_definition', 'is_resource_gdr',
    'PoolSnapshot', 'CumulativeSnapshot',
    'compute_per_pool_snapshots', 'compute_cumulative_snapshots',
    'compute_per_pool_snapshots_batch', 'compute_cumulative_snapshots_batch',
    'per_pool_summary_stats', 'cumulative_gdr_at_pool_ends',
    'TransitionMatrix', 'compute_transition_matrices',
    'compute_transition_matrices_from_flags', 'compute_transition_flags_from_gdr',
    'ForwardStep', 'BackwardStep', 'ForwardResult', 'BackwardResult',
    'VulnerabilityInterval', 'PityStatSnapshot', 'PoolVulnerabilityResult', 'VulnerabilityAnalysisResult',
    'compute_vulnerability_analysis', 'plot_vulnerability', 'plot_vulnerability_ridge',
    'WorstImpactAnalyzer', 'WorstImpactResult', 'ConditionalResourceDistribution',
    'DrawTargetStrategy',
    'StreamingAnalyzer', 'StreamingSuccessCounter', 'SharedResultCollector', 'DrawSequenceExtractor', 'extract_aggregate', 'extract_process', 'WorkerLocalExtractor', 'merge_extraction_packets',
    'PoolEvent', 'SampleTrace', 'infer_events', 'compute_pool_gdr_cumulative', 'compute_pool_gdr_single_pool',
    'compute_aa', 'compute_bb', 'compute_ab', 'compute_ba',
    'to_event_type_sequence', 'to_event_type_set', 'to_custom_pattern', 'to_raw_trajectory',
    'to_success_sequence', 'to_success_set', 'to_success_count', 'to_success_custom',
    'EVENT_MODE_MAP', 'SUCCESS_MODE_MAP',
    'ResultStore', 'StoredDataset', 'ComparabilityFingerprint', 'ComparabilityDiff', 'compute_config_hash',
    'BinningResult', 'compute_bins', 'detect_step_size', 'compute_aligned_bins',
    'DescriptiveStats', 'HypothesisTestResult', 'ParetoFrontier',
    'dd_bootstrap_test', 'compute_dominance_matrix', 'compute_pvalue_matrix',
    'compute_gdr_values_for_datasets', 'holm_bonferroni', 'benjamini_hochberg',
]


def __getattr__(name):
    """惰性导入重依赖符号，避免 import gacha_simulator.core 时级联加载 scipy。

    Windows spawn 下每个 worker 进程 import gacha_simulator.service
    → core/__init__.py → bootstrap.py → scipy.stats，若 4 个 worker
    同时加载 scipy 大 DLL 可触发页面文件耗尽 (ImportError: DLL load
    failed: 页面文件太小)。BootstrapEngine 仅被 GUI analysis_panel 使用，
    在 worker 进程中永不调用，没必要在 spawn 关键路径上加载。
    """
    if name in ('BootstrapEngine', 'BootstrapResult'):
        from .bootstrap import BootstrapEngine, BootstrapResult  # noqa: F401
        val = locals()[name]
        globals()[name] = val  # 缓存，后续访问不再经过 __getattr__
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
