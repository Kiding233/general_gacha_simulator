from .result_types import CompactResult
from .collector import SimulationCollector, InfoVectorCollector, CompactCollector
from .pool import Pool, Reward, CostOption, PoolCost, parse_cost_string, cost_to_string
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
from .resource_gain import ResourceGainFunction, LinearResourceGain, PeriodicResourceGain, StepResourceGain, CompositeResourceGain, ScheduleResourceGain
from .generalized_drop_rate import (
    GeneralizedDropRate, RarityValueAtT, CumulativeResourceEfficiency, PityProgressAtT,
    DropRateBetweenT1T2, TotalValueAtT, TargetCardCountAtT, TargetCardPercentageAtT, TargetCardEfficiencyAtT
)
from .schedule import PoolSchedule, PoolScheduleManager
from .target_card import TargetCard, TargetCardSet
from .gdr_analysis import (
    SuccessProbabilityAnalyzer, GDRCalculator,
    compute_gdr_count, compute_gdr_percentage, compute_gdr_efficiency
)
from .pool_config import PoolConfig, CardDef, CardCatalog, parse_schedule_file, parse_distribution_file, parse_cards_file, load_config_from_directory
from .distribution import EmpiricalDistribution, DistributionSummary, JointSamples, WorstCaseAnalysis, BestCaseAnalysis
from .risk_analysis import RiskAnalyzer
from .gdr import GDRContext, GDR_REGISTRY, COMPACT_GDR_REGISTRY, UNIFIED_GDR_REGISTRY, register_gdr, SuccessChecker, GDRDefinition, populate_gdr_combo, get_default_threshold, compute_gdr_from_compact, compute_gdr_from_cumulative, compute_success_probability
from .per_pool_analysis import (
    PoolSnapshot, CumulativeSnapshot,
    compute_per_pool_snapshots, compute_cumulative_snapshots,
    compute_per_pool_snapshots_batch, compute_cumulative_snapshots_batch,
    per_pool_summary_stats, cumulative_gdr_at_pool_ends,
    TransitionMatrix, compute_transition_matrices,
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
from .streaming import StreamingAnalyzer, StreamingSuccessCounter, SharedResultCollector, DrawSequenceExtractor, extract_aggregate, extract_process
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
    'Pool', 'Reward', 'CostOption', 'PoolCost', 'parse_cost_string', 'cost_to_string',
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
    'STRATEGY_REGISTRY', 'create_strategy',
    'StopCondition', 'FixedActionCountCondition', 'ResourceThresholdCondition',
    'TargetAcquiredCondition', 'TimeLimitCondition', 'CompositeStopCondition',
    'AllPoolsEndCondition', 'LastDrawCardCondition',
    'STOP_CONDITION_REGISTRY', 'create_stop_condition',
    'stop_condition_type_to_key', 'stop_condition_key_to_type',
    'ResourceGainFunction', 'LinearResourceGain', 'PeriodicResourceGain', 'StepResourceGain', 'CompositeResourceGain', 'ScheduleResourceGain',
    'GeneralizedDropRate', 'RarityValueAtT', 'CumulativeResourceEfficiency', 'PityProgressAtT',
    'DropRateBetweenT1T2', 'TotalValueAtT', 'TargetCardCountAtT', 'TargetCardPercentageAtT', 'TargetCardEfficiencyAtT',
    'PoolSchedule', 'PoolScheduleManager',
    'TargetCard', 'TargetCardSet',
    'SuccessProbabilityAnalyzer', 'GDRCalculator',
    'compute_gdr_count', 'compute_gdr_percentage', 'compute_gdr_efficiency',
    'PoolConfig', 'CardDef', 'CardCatalog', 'parse_schedule_file', 'parse_distribution_file', 'parse_cards_file', 'load_config_from_directory',
    'EmpiricalDistribution', 'DistributionSummary', 'JointSamples', 'WorstCaseAnalysis', 'BestCaseAnalysis',
    'RiskAnalyzer',
    'GDRContext', 'GDR_REGISTRY', 'COMPACT_GDR_REGISTRY', 'UNIFIED_GDR_REGISTRY', 'register_gdr', 'SuccessChecker', 'GDRDefinition', 'populate_gdr_combo', 'get_default_threshold', 'compute_gdr_from_compact', 'compute_gdr_from_cumulative', 'compute_success_probability',
    'PoolSnapshot', 'CumulativeSnapshot',
    'compute_per_pool_snapshots', 'compute_cumulative_snapshots',
    'compute_per_pool_snapshots_batch', 'compute_cumulative_snapshots_batch',
    'per_pool_summary_stats', 'cumulative_gdr_at_pool_ends',
    'TransitionMatrix', 'compute_transition_matrices',
    'ForwardStep', 'BackwardStep', 'ForwardResult', 'BackwardResult',
    'VulnerabilityInterval', 'PityStatSnapshot', 'PoolVulnerabilityResult', 'VulnerabilityAnalysisResult',
    'compute_vulnerability_analysis', 'plot_vulnerability', 'plot_vulnerability_ridge',
    'WorstImpactAnalyzer', 'WorstImpactResult', 'ConditionalResourceDistribution',
    'DrawTargetStrategy',
    'StreamingAnalyzer', 'StreamingSuccessCounter', 'SharedResultCollector', 'DrawSequenceExtractor', 'extract_aggregate', 'extract_process',
    'PoolEvent', 'SampleTrace', 'infer_events', 'compute_pool_gdr_cumulative', 'compute_pool_gdr_single_pool',
    'compute_aa', 'compute_bb', 'compute_ab', 'compute_ba',
    'to_event_type_sequence', 'to_event_type_set', 'to_custom_pattern', 'to_raw_trajectory',
    'to_success_sequence', 'to_success_set', 'to_success_count', 'to_success_custom',
    'EVENT_MODE_MAP', 'SUCCESS_MODE_MAP',
]
