"""额外资源（first_time_bonus / nth_time_bonus / excess_bonus）测试"""
import pytest
from gacha_simulator.core.pool import Reward, compute_bonus_resources


def test_first_time_bonus_applied():
    """首次获得卡时触发 first_time_bonus"""
    reward = Reward(
        id="card_A", name="A",
        first_time_bonus={"gem": 50},
    )
    bonus = compute_bonus_resources(reward, acquired_before=0, acquired_after=1)
    assert bonus == {"gem": 50}


def test_first_time_bonus_not_on_second():
    """第二次获得时不触发 first_time_bonus"""
    reward = Reward(
        id="card_A", name="A",
        first_time_bonus={"gem": 50},
    )
    bonus = compute_bonus_resources(reward, acquired_before=1, acquired_after=2)
    assert bonus == {}


def test_nth_time_bonus_exact():
    """第N次获得时触发 nth_time_bonus"""
    reward = Reward(
        id="card_A", name="A",
        nth_time_bonus={3: {"gem": 100}},
    )
    bonus = compute_bonus_resources(reward, acquired_before=2, acquired_after=3)
    assert bonus == {"gem": 100}


def test_nth_time_bonus_not_on_other_n():
    """非指定次数不触发"""
    reward = Reward(
        id="card_A", name="A",
        nth_time_bonus={3: {"gem": 100}},
    )
    bonus = compute_bonus_resources(reward, acquired_before=3, acquired_after=4)
    assert bonus == {}


def test_nth_time_bonus_multiple_n():
    """多个不同N次奖励"""
    reward = Reward(
        id="card_A", name="A",
        nth_time_bonus={
            2: {"gem": 50},
            5: {"gem": 200},
        },
    )
    bonus = compute_bonus_resources(reward, acquired_before=4, acquired_after=5)
    assert bonus == {"gem": 200}


def test_excess_bonus_above_threshold():
    """超出阈值后触发 excess_bonus"""
    reward = Reward(
        id="card_A", name="A",
        excess_bonus={"threshold": 5, "resources": {"starlight": 25}},
    )
    bonus = compute_bonus_resources(reward, acquired_before=7, acquired_after=8)
    assert bonus == {"starlight": 25}


def test_excess_bonus_below_threshold():
    """未超阈值不触发 excess_bonus"""
    reward = Reward(
        id="card_A", name="A",
        excess_bonus={"threshold": 5, "resources": {"starlight": 25}},
    )
    bonus = compute_bonus_resources(reward, acquired_before=3, acquired_after=4)
    assert bonus == {}


def test_excess_bonus_default_threshold():
    """未设置 threshold 时默认极高，不触发"""
    reward = Reward(
        id="card_A", name="A",
        excess_bonus={"resources": {"starlight": 25}},
    )
    bonus = compute_bonus_resources(reward, acquired_before=3, acquired_after=4)
    assert bonus == {}


def test_combined_bonuses():
    """同时触发多种额外奖励"""
    reward = Reward(
        id="card_A", name="A",
        first_time_bonus={"gem": 50},
        nth_time_bonus={3: {"gem": 100}},
    )
    bonus = compute_bonus_resources(reward, acquired_before=0, acquired_after=1)
    assert bonus == {"gem": 50}

    bonus = compute_bonus_resources(reward, acquired_before=2, acquired_after=3)
    assert bonus == {"gem": 100}


def test_no_bonus_reward():
    """无任何额外奖励的卡"""
    reward = Reward(id="card_A", name="A")
    bonus = compute_bonus_resources(reward, acquired_before=0, acquired_after=1)
    assert bonus == {}
    bonus = compute_bonus_resources(reward, acquired_before=5, acquired_after=6)
    assert bonus == {}


def test_first_time_bonus_with_initial_count():
    """初始持有 >0 时不触发 first_time_bonus（P9 预填入确保 acquired_before >= 1）"""
    reward = Reward(
        id="card_A", name="A",
        first_time_bonus={"gem": 50},
    )
    bonus = compute_bonus_resources(reward, acquired_before=1, acquired_after=2)
    assert bonus == {}
