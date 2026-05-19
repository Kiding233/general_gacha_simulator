from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


class Action(ABC):
    type: str

    @abstractmethod
    def __repr__(self) -> str:
        pass


@dataclass
class DrawAction(Action):
    pool_id: str
    type: Literal['draw'] = 'draw'

    def __repr__(self) -> str:
        return f"DrawAction(pool_id='{self.pool_id}')"


@dataclass
class WaitAction(Action):
    duration: float
    type: Literal['wait'] = 'wait'

    def __repr__(self) -> str:
        return f"WaitAction(duration={self.duration})"
