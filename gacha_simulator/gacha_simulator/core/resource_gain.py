import calendar
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .state import GachaState


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
    import datetime
    d = datetime.date.fromordinal(day + 735000)
    return d.isoweekday()


def _month_of_day(day: int) -> int:
    import datetime
    d = datetime.date.fromordinal(day + 735000)
    return d.month


def _day_of_month(day: int) -> int:
    import datetime
    d = datetime.date.fromordinal(day + 735000)
    return d.day


def _week_of_month(day: int) -> int:
    import datetime
    d = datetime.date.fromordinal(day + 735000)
    return (d.day - 1) // 7 + 1


def parse_gains_file(filepath: str, total_days: int = 365) -> Dict[int, Dict[str, float]]:
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
                target_day = int(rule_name.split(':')[1].strip())
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
