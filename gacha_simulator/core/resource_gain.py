import logging
import datetime as _dt
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .state import GachaState
    from .config_store import GainRule, DayOverride

logger = logging.getLogger(__name__)


class ResourceGainFunction(ABC):
    @abstractmethod
    def compute(self, elapsed_time: float, state: 'GachaState') -> Dict[str, float]:
        pass

    @abstractmethod
    def description(self) -> str:
        pass


class ScheduleResourceGain(ResourceGainFunction):
    DAY = 86400

    def __init__(self, schedule: Dict[int, Dict[str, float]], total_days: int = 365):
        self.schedule = schedule
        self.total_days = total_days

    def compute(self, elapsed_time: float, state: 'GachaState') -> Dict[str, float]:
        current_day = int(state.real_time // self.DAY)
        new_day = int((state.real_time + elapsed_time) // self.DAY)

        result: Dict[str, float] = {}
        for day in range(current_day + 1, new_day + 1):
            day_gains = self.schedule.get(day)
            if day_gains:
                for resource, amount in day_gains.items():
                    result[resource] = result.get(resource, 0) + amount

        return result

    def description(self) -> str:
        return f"按天获取: {len(self.schedule)} 天有资源收入"


class LinearResourceGain(ResourceGainFunction):
    def __init__(self, rate: Dict[str, float]):
        self.rate = rate

    def compute(self, elapsed_time: float, state: 'GachaState') -> Dict[str, float]:
        return {k: v * elapsed_time for k, v in self.rate.items()}

    def description(self) -> str:
        rates = ', '.join(f"{k}={v}/s" for k, v in self.rate.items())
        return f"线性获取: {rates}"


class CompositeResourceGain(ResourceGainFunction):
    def __init__(self, functions: list):
        self.functions = functions

    def compute(self, elapsed_time: float, state: 'GachaState') -> Dict[str, float]:
        result = {}
        for func in self.functions:
            gains = func.compute(elapsed_time, state)
            for k, v in gains.items():
                result[k] = result.get(k, 0) + v
        return result

    def description(self) -> str:
        return ' + '.join(f.description() for f in self.functions)


class PeriodicResourceGain(ResourceGainFunction):
    def __init__(self, period: float, reward: Dict[str, float]):
        self.period = period
        self.reward = reward

    def compute(self, elapsed_time: float, state: 'GachaState') -> Dict[str, float]:
        periods = int(elapsed_time // self.period)
        if periods <= 0:
            return {}
        return {k: v * periods for k, v in self.reward.items()}

    def description(self) -> str:
        rewards = ', '.join(f"{k}={v}" for k, v in self.reward.items())
        return f"周期获取(每{self.period}s): {rewards}"


class StepResourceGain(ResourceGainFunction):
    def __init__(self, steps: List[Tuple[float, Dict[str, float]]]):
        self.steps = sorted(steps, key=lambda x: x[0])

    def compute(self, elapsed_time: float, state: 'GachaState') -> Dict[str, float]:
        result: Dict[str, float] = {}
        for threshold, reward in self.steps:
            if elapsed_time >= threshold:
                for k, v in reward.items():
                    result[k] = result.get(k, 0) + v
        return result

    def description(self) -> str:
        return f"阶梯获取: {len(self.steps)} 个阶梯"


def _parse_resource_amount(text: str) -> Dict[str, float]:
    result = {}
    for part in text.split(','):
        part = part.strip()
        if ':' in part:
            rid, amt = part.split(':', 1)
            result[rid.strip()] = float(amt.strip())
    return result


def _weekday_of_day(day: int) -> int:
    """[DEPRECATED] 由 expand_gain_rules_to_schedule() 内联取代。"""
    import datetime
    d = datetime.date.fromordinal(day + 735000)
    return d.isoweekday()


def _month_of_day(day: int) -> int:
    """[DEPRECATED] 由 expand_gain_rules_to_schedule() 内联取代。"""
    import datetime
    d = datetime.date.fromordinal(day + 735000)
    return d.month


def _day_of_month(day: int) -> int:
    """[DEPRECATED] 由 expand_gain_rules_to_schedule() 内联取代。"""
    import datetime
    d = datetime.date.fromordinal(day + 735000)
    return d.day


def _week_of_month(day: int) -> int:
    """[DEPRECATED] 由 expand_gain_rules_to_schedule() 内联取代。"""
    import datetime
    d = datetime.date.fromordinal(day + 735000)
    return (d.day - 1) // 7 + 1


# ── 默认模拟起始日期（ordinal=735000 → 2013-06-02）──
_DEFAULT_START_DATE = _dt.date(2013, 6, 2)


def expand_gain_rules_to_schedule(
    gain_rules: List['GainRule'],
    day_overrides: List['DayOverride'],
    total_days: int,
    start_date: Optional[_dt.date] = None,
) -> Dict[int, Dict[str, float]]:
    """将资源获取规则展开为 {day: {resource_id: amount}} 字典。

    统一了 _build_resource_gain() 内联展开逻辑与 parse_gains_file() 正确日历算法，
    消除两条路径的代码重复与行为不一致。

    Args:
        gain_rules: 规则列表（GainRule 对象）。
        day_overrides: 指定日期覆盖列表（DayOverride 对象）。
        total_days: 模拟总天数。
        start_date: day=0 对应的真实日期，默认为 2013-06-02。

    Returns:
        {day: {rid: amount}} 字典，key 为绝对天数偏移。

    Raises:
        不抛出异常——所有参数错误均通过 logging.warning 报告并回退默认值。
    """
    if start_date is None:
        start_date = _DEFAULT_START_DATE

    if total_days <= 0:
        return {}

    schedule: Dict[int, Dict[str, float]] = {}
    start_ordinal = start_date.toordinal()

    for rule in gain_rules:
        rule_type = getattr(rule, 'rule_type', 'every_n_days')
        param = getattr(rule, 'param', '1')
        gains = dict(getattr(rule, 'gains', {}) or {})

        if not gains:
            continue

        if rule_type == 'every_n_days':
            # ── 参数解析 + 空值防御 + 范围校验 ──
            n = 1
            try:
                n = int(param) if param else 1
            except (ValueError, TypeError):
                logger.warning(
                    "expand_gain_rules_to_schedule: every_n_days 参数 '%s' 无效，回退 n=1", param)
                n = 1
            if n <= 0:
                logger.warning(
                    "expand_gain_rules_to_schedule: every_n_days n=%d <= 0，回退 n=1", n)
                n = 1
            for day in range(0, total_days, n):
                if day not in schedule:
                    schedule[day] = {}
                for rid, amount in gains.items():
                    schedule[day][rid] = schedule[day].get(rid, 0) + float(amount)

        elif rule_type == 'weekly':
            # ── 参数解析 + 空值防御 + 范围校验 ──
            target_wday = 1
            try:
                target_wday = int(param) if param else 1
            except (ValueError, TypeError):
                logger.warning(
                    "expand_gain_rules_to_schedule: weekly 参数 '%s' 无效，回退 weekday=1", param)
                target_wday = 1
            if not (1 <= target_wday <= 7):
                logger.warning(
                    "expand_gain_rules_to_schedule: weekly weekday=%d 越界 [1,7]，回退 weekday=1",
                    target_wday)
                target_wday = 1
            for day in range(total_days):
                try:
                    d = _dt.date.fromordinal(start_ordinal + day)
                    if d.isoweekday() == target_wday:
                        if day not in schedule:
                            schedule[day] = {}
                        for rid, amount in gains.items():
                            schedule[day][rid] = schedule[day].get(rid, 0) + float(amount)
                except Exception:
                    pass

        elif rule_type == 'monthly_day':
            # ── 空 param 防御 ──
            if not param or not param.strip():
                logger.warning(
                    "expand_gain_rules_to_schedule: monthly_day 参数为空，回退 day=1")
                # 单数字逻辑：每月第1天
                for day in range(total_days):
                    try:
                        d = _dt.date.fromordinal(start_ordinal + day)
                        if d.day == 1:
                            if day not in schedule:
                                schedule[day] = {}
                            for rid, amount in gains.items():
                                schedule[day][rid] = schedule[day].get(rid, 0) + float(amount)
                    except Exception:
                        pass
                continue

            # ── 分支判断：先检查是否含逗号（月,日格式）──
            if ',' in param:
                # 月,日格式：每年指定月日触发
                parts = param.split(',')
                if len(parts) != 2:
                    logger.warning(
                        "expand_gain_rules_to_schedule: monthly_day 月,日格式 '%s' 无法解析，跳过该规则", param)
                    continue
                try:
                    target_month = int(parts[0].strip())
                    target_day = int(parts[1].strip())
                except (ValueError, TypeError):
                    logger.warning(
                        "expand_gain_rules_to_schedule: monthly_day 月,日参数 '%s' 转换失败，跳过该规则", param)
                    continue
                # 范围校验
                if not (1 <= target_month <= 12) or not (1 <= target_day <= 31):
                    logger.warning(
                        "expand_gain_rules_to_schedule: monthly_day 月=%d 日=%d 越界，跳过该规则",
                        target_month, target_day)
                    continue
                for day in range(total_days):
                    try:
                        d = _dt.date.fromordinal(start_ordinal + day)
                        if d.month == target_month and d.day == target_day:
                            if day not in schedule:
                                schedule[day] = {}
                            for rid, amount in gains.items():
                                schedule[day][rid] = schedule[day].get(rid, 0) + float(amount)
                    except Exception:
                        pass
            else:
                # 单数字：每月第 N 天
                try:
                    target_day = int(param)
                except (ValueError, TypeError):
                    logger.warning(
                        "expand_gain_rules_to_schedule: monthly_day 单数字参数 '%s' 无效，回退 day=1", param)
                    target_day = 1
                if not (1 <= target_day <= 31):
                    logger.warning(
                        "expand_gain_rules_to_schedule: monthly_day day=%d 越界 [1,31]，回退 day=1",
                        target_day)
                    target_day = 1
                for day in range(total_days):
                    try:
                        d = _dt.date.fromordinal(start_ordinal + day)
                        if d.day == target_day:
                            if day not in schedule:
                                schedule[day] = {}
                            for rid, amount in gains.items():
                                schedule[day][rid] = schedule[day].get(rid, 0) + float(amount)
                    except Exception:
                        pass

        elif rule_type == 'monthly_week':
            # ── 空 param 防御 ──
            if not param or not param.strip():
                logger.warning(
                    "expand_gain_rules_to_schedule: monthly_week 参数为空，跳过该规则")
                continue

            # ── 分隔符解析：先尝试逗号，失败则尝试减号（旧格式兼容）──
            parts = param.split(',')
            if len(parts) != 2:
                parts = param.split('-')
            if len(parts) != 2:
                logger.warning(
                    "expand_gain_rules_to_schedule: monthly_week 参数 '%s' 无法解析（需 week,day 格式），跳过该规则", param)
                continue
            try:
                target_week = int(parts[0].strip())
                target_wday = int(parts[1].strip())
            except (ValueError, TypeError):
                logger.warning(
                    "expand_gain_rules_to_schedule: monthly_week 参数 '%s' 转换失败，跳过该规则", param)
                continue
            # 范围校验
            if not (1 <= target_week <= 5) or not (1 <= target_wday <= 7):
                logger.warning(
                    "expand_gain_rules_to_schedule: monthly_week week=%d wday=%d 越界，跳过该规则",
                    target_week, target_wday)
                continue

            for day in range(total_days):
                try:
                    d = _dt.date.fromordinal(start_ordinal + day)
                    week_of_month = (d.day - 1) // 7 + 1
                    if week_of_month == target_week and d.isoweekday() == target_wday:
                        if day not in schedule:
                            schedule[day] = {}
                        for rid, amount in gains.items():
                            schedule[day][rid] = schedule[day].get(rid, 0) + float(amount)
                except Exception:
                    pass

    # ── day: 覆盖（累加语义，与 _build_resource_gain 行为一致）──
    for override in day_overrides:
        day = getattr(override, 'day', 0)
        override_gains = getattr(override, 'gains', {}) or {}
        if 0 <= day < total_days:
            if day not in schedule:
                schedule[day] = {}
            for rid, amount in override_gains.items():
                amount = float(amount)
                if amount > 0:
                    schedule[day][rid] = schedule[day].get(rid, 0) + amount

    return schedule


def parse_gains_file(filepath: str, total_days: int = 365) -> Dict[int, Dict[str, float]]:
    """[DEPRECATED] 直接读取 gains.txt 文件展开为 schedule dict。

    此函数已被 expand_gain_rules_to_schedule() 取代——新函数通过 ConfigStore
    获取已归一化的 GainRule/DayOverride 对象，消除文件绕过、日历 bug 和代码重复。
    保留此函数以防外部脚本调用，新代码请使用 expand_gain_rules_to_schedule()。
    """
    import warnings
    warnings.warn(
        "parse_gains_file is deprecated, use expand_gain_rules_to_schedule() instead",
        DeprecationWarning, stacklevel=2)
    schedule: Dict[int, Dict[str, float]] = {}

    rules: List[Tuple[str, dict]] = []
    day_overrides: Dict[int, Dict[str, float]] = {}

    current_rule = None
    current_gains: Dict[str, float] = {}

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if line.startswith('[') and line.endswith(']'):
                if current_rule is not None and current_gains:
                    rules.append((current_rule, current_gains.copy()))
                current_rule = line[1:-1].strip()
                current_gains = {}
                continue

            if line.startswith('day:'):
                if current_rule is not None and current_gains:
                    rules.append((current_rule, current_gains.copy()))
                    current_rule = None
                    current_gains = {}

                rest = line[4:].strip()
                parts = rest.split('|', 1)
                if len(parts) == 2:
                    day_num = int(parts[0].strip())
                    gains = _parse_resource_amount(parts[1].strip())
                    if day_num not in day_overrides:
                        day_overrides[day_num] = {}
                    for r, a in gains.items():
                        day_overrides[day_num][r] = day_overrides[day_num].get(r, 0) + a
                continue

            if current_rule is not None:
                gains = _parse_resource_amount(line)
                for r, a in gains.items():
                    current_gains[r] = current_gains.get(r, 0) + a

    if current_rule is not None and current_gains:
        rules.append((current_rule, current_gains.copy()))

    for day in range(total_days):
        for rule_name, rule_gains in rules:
            if rule_name.startswith('every_n_days:'):
                n = int(rule_name.split(':')[1].strip())
                if day % n == 0:
                    if day not in schedule:
                        schedule[day] = {}
                    for r, a in rule_gains.items():
                        schedule[day][r] = schedule[day].get(r, 0) + a

            elif rule_name.startswith('weekly:'):
                target_weekday = int(rule_name.split(':')[1].strip())
                if _weekday_of_day(day) == target_weekday:
                    if day not in schedule:
                        schedule[day] = {}
                    for r, a in rule_gains.items():
                        schedule[day][r] = schedule[day].get(r, 0) + a

            elif rule_name.startswith('monthly_day:'):
                param = rule_name.split(':', 1)[1].strip()
                if ',' in param:
                    # 格式: month,day —— 每年指定月日触发一次
                    parts = param.split(',')
                    if len(parts) == 2:
                        target_month = int(parts[0].strip())
                        target_day = int(parts[1].strip())
                        if _month_of_day(day) == target_month and _day_of_month(day) == target_day:
                            if day not in schedule:
                                schedule[day] = {}
                            for r, a in rule_gains.items():
                                schedule[day][r] = schedule[day].get(r, 0) + a
                else:
                    # 格式: day —— 每月第 N 天触发
                    target_day = int(param)
                    if _day_of_month(day) == target_day:
                        if day not in schedule:
                            schedule[day] = {}
                        for r, a in rule_gains.items():
                            schedule[day][r] = schedule[day].get(r, 0) + a

            elif rule_name.startswith('monthly_week:'):
                params = rule_name.split(':')[1].strip()
                parts = params.split(',')
                if len(parts) == 2:
                    target_week = int(parts[0].strip())
                    target_weekday = int(parts[1].strip())
                    if _week_of_month(day) == target_week and _weekday_of_day(day) == target_weekday:
                        if day not in schedule:
                            schedule[day] = {}
                        for r, a in rule_gains.items():
                            schedule[day][r] = schedule[day].get(r, 0) + a

    for day, gains in day_overrides.items():
        if day not in schedule:
            schedule[day] = {}
        for r, a in gains.items():
            schedule[day][r] = a

    return schedule


def parse_resources_file(filepath: str) -> Dict[str, str]:
    resources = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('|')
                if len(parts) >= 2:
                    rid = parts[0].strip()
                    name = parts[1].strip()
                    resources[rid] = name
    except FileNotFoundError:
        pass
    return resources
