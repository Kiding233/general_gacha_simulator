from gacha_simulator.core.target_card import TargetCard, TargetCardSet


def test_target_card():
    card = TargetCard('character_a', ['pool1', 'pool2'], quantity_needed=2, priority=1)
    assert card.is_in_pool('pool1') is True
    assert card.is_in_pool('pool3') is False


def test_target_card_set():
    targets = [
        TargetCard('a', ['p1'], 1, priority=2),
        TargetCard('b', ['p1', 'p2'], 2, priority=1),
    ]
    tcs = TargetCardSet(targets)
    assert tcs.get_quantity_needed('a') == 1
    assert tcs.get_quantity_needed('c') == 0
    assert len(tcs.get_cards_by_pool('p2')) == 1
    unfinished = tcs.get_unfinished_targets({'a': 1, 'b': 0})
    assert len(unfinished) == 1
    assert unfinished[0].card_id == 'b'
