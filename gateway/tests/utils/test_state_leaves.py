from radicalbit_ai_gateway.utils.state_leaves import string_leaves, with_string_leaves

STATE = {
    'ticket': 'My card was charged twice',
    'amount': 42.5,
    'refunded': False,
    'customer': {'name': 'Ada', 'tier': 'gold', 'orders': 3},
    'notes': ['first', {'text': 'second'}, None, 7],
}


def test_string_leaves_are_listed_depth_first():
    assert string_leaves(STATE) == [
        'My card was charged twice',
        'Ada',
        'gold',
        'first',
        'second',
    ]


def test_keys_are_not_leaves():
    assert string_leaves({'secret@example.com': 1}) == []


def test_a_bare_string_is_its_own_leaf():
    assert string_leaves('hello') == ['hello']


def test_with_string_leaves_rewrites_the_leaves_and_keeps_the_structure():
    texts = ['A', 'B', 'C', 'D', 'E']

    assert with_string_leaves(STATE, texts) == {
        'ticket': 'A',
        'amount': 42.5,
        'refunded': False,
        'customer': {'name': 'B', 'tier': 'C', 'orders': 3},
        'notes': ['D', {'text': 'E'}, None, 7],
    }


def test_with_string_leaves_leaves_the_input_unchanged():
    state = {'a': ['x']}

    with_string_leaves(state, ['y'])

    assert state == {'a': ['x']}
