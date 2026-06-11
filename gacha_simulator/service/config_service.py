import json
from pathlib import Path
from typing import Dict, Any, List
from ..core import Pool, Reward


class ConfigService:
    def __init__(self, config_dir: str = 'data/config'):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def save_config(self, name: str, config: Dict[str, Any]) -> None:
        path = self.config_dir / f'{name}.json'
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def load_config(self, name: str) -> Dict[str, Any]:
        path = self.config_dir / f'{name}.json'
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def list_configs(self) -> List[str]:
        return [p.stem for p in self.config_dir.glob('*.json')]

    def export_pool_to_config(self, pools: List[Pool]) -> Dict[str, Any]:
        return {
            'pools': [
                {
                    'id': p.id,
                    'name': p.name,
                    'cost': p.cost,
                    'rewards': [
                        {'id': r.id, 'name': r.name, 'probability': prob}
                        for r, prob in p.rewards
                    ],
                    'available_from': p.available_from,
                    'available_until': p.available_until,
                    'is_exchange': p.is_exchange,
                }
                for p in pools
            ]
        }

    def import_pool_from_config(self, config: Dict[str, Any]) -> List[Pool]:
        pools = []
        for p_data in config.get('pools', []):
            rewards = [
                (Reward(r['id'], r['name']), r['probability'])
                for r in p_data.get('rewards', [])
            ]
            pools.append(Pool(
                id=p_data['id'],
                name=p_data['name'],
                cost=p_data.get('cost', {}),
                rewards=rewards,
                available_from=p_data.get('available_from'),
                available_until=p_data.get('available_until'),
                is_exchange=p_data.get('is_exchange', False),
            ))
        return pools
