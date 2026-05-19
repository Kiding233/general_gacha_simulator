class InfoVector:
    __slots__ = ('action_type', 'card_id', 'pool_id', 'resources_consumed',
                 'resources_gained', 'real_time_before', 'real_time_after',
                 'time_elapsed', 'pity_state', 'action_index', 'session_id',
                 'free_params', 'pity_triggered')

    def __init__(self, action_type='draw', card_id=None, pool_id=None,
                 resources_consumed=None, resources_gained=None,
                 real_time_before=0.0, real_time_after=0.0,
                 time_elapsed=0.0, pity_state=None, action_index=0,
                 session_id='', free_params=None, pity_triggered=False):
        self.action_type = action_type
        self.card_id = card_id
        self.pool_id = pool_id
        self.resources_consumed = resources_consumed or {}
        self.resources_gained = resources_gained or {}
        self.real_time_before = real_time_before
        self.real_time_after = real_time_after
        self.time_elapsed = time_elapsed
        self.pity_state = pity_state or {}
        self.action_index = action_index
        self.session_id = session_id
        self.free_params = free_params or {}
        self.pity_triggered = pity_triggered

    @property
    def time_delta(self) -> float:
        return self.real_time_after - self.real_time_before

    def __reduce__(self):
        return (_reconstruct_iv, (
            self.action_type, self.card_id, self.pool_id,
            self.resources_consumed, self.resources_gained,
            self.real_time_before, self.real_time_after,
            self.time_elapsed, self.pity_state, self.action_index,
            self.session_id, self.free_params, self.pity_triggered,
        ))


def _reconstruct_iv(action_type, card_id, pool_id, resources_consumed,
                    resources_gained, real_time_before, real_time_after,
                    time_elapsed, pity_state, action_index, session_id,
                    free_params, pity_triggered):
    iv = InfoVector.__new__(InfoVector)
    iv.action_type = action_type
    iv.card_id = card_id
    iv.pool_id = pool_id
    iv.resources_consumed = resources_consumed
    iv.resources_gained = resources_gained
    iv.real_time_before = real_time_before
    iv.real_time_after = real_time_after
    iv.time_elapsed = time_elapsed
    iv.pity_state = pity_state
    iv.action_index = action_index
    iv.session_id = session_id
    iv.free_params = free_params
    iv.pity_triggered = pity_triggered
    return iv
