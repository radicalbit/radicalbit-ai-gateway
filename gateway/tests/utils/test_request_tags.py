import pytest

from radicalbit_ai_gateway.utils.exceptions import (
    TagsHeaderMalformed,
    TagsHeaderTooLarge,
    TagsKeyInvalid,
    TagsValueInvalid,
)
from radicalbit_ai_gateway.utils.request_tags import (
    MAX_TAG_KEY_LENGTH,
    MAX_TAG_VALUE_LENGTH,
    MAX_TAGS_HEADER_BYTES,
    parse_tags_header,
)


def test_parses_the_documented_example():
    assert parse_tags_header('cost_center=retail,env=prod,app=leonardo-clm') == (
        'app=leonardo-clm',
        'cost_center=retail',
        'env=prod',
    )


@pytest.mark.parametrize('raw', [None, '', '   ', '\t'])
def test_absent_or_blank_header_yields_no_tags(raw):
    assert parse_tags_header(raw) == ()


def test_result_is_independent_of_header_order():
    """Same tags in any order must produce byte-identical ClickHouse rows."""
    assert parse_tags_header('env=prod,app=x,cost_center=retail') == parse_tags_header(
        'cost_center=retail,env=prod,app=x'
    )


def test_same_key_with_different_values_keeps_both():
    assert parse_tags_header('env=prod,env=staging') == ('env=prod', 'env=staging')


def test_identical_key_and_value_is_deduplicated():
    assert parse_tags_header('env=prod,env=prod') == ('env=prod',)


def test_duplicate_removed_while_other_values_of_the_same_key_survive():
    assert parse_tags_header('env=prod,env=staging,env=prod') == (
        'env=prod',
        'env=staging',
    )


def test_whitespace_around_pairs_and_separator_is_trimmed():
    assert parse_tags_header('  env = prod , app=x ') == ('app=x', 'env=prod')


def test_a_header_at_exactly_the_byte_limit_is_accepted():
    # 241 tags of 16 bytes joined by 240 commas: 4096 bytes on the nose,
    # with every value short enough to also pass the per-value limit.
    raw = ','.join(['k=' + 'v' * 14] * 241)
    assert len(raw.encode('utf-8')) == MAX_TAGS_HEADER_BYTES
    assert parse_tags_header(raw) == ('k=' + 'v' * 14,)


def test_a_single_tag_sized_to_the_header_limit_hits_the_value_limit_first():
    raw = 'k=' + 'v' * (MAX_TAGS_HEADER_BYTES - 2)
    assert len(raw.encode('utf-8')) == MAX_TAGS_HEADER_BYTES
    with pytest.raises(TagsValueInvalid):
        parse_tags_header(raw)


def test_oversized_header_is_rejected():
    raw = 'a=1,' * 2000
    with pytest.raises(TagsHeaderTooLarge) as err:
        parse_tags_header(raw)
    assert err.value.code == 'tags_header_too_large'
    assert err.value.status_code == 400
    assert str(len(raw.encode('utf-8'))) in err.value.client_message
    assert str(MAX_TAGS_HEADER_BYTES) in err.value.client_message


def test_size_limit_counts_bytes_not_characters():
    raw = 'k=' + 'é' * MAX_TAGS_HEADER_BYTES
    with pytest.raises(TagsHeaderTooLarge):
        parse_tags_header(raw)


@pytest.mark.parametrize(
    'raw',
    [
        'env',  # no '='
        '=prod',  # empty key
        'env=',  # empty value
        'a=1,,b=2',  # empty segment
        'a=1,',  # trailing comma
        ',a=1',  # leading comma
        'a=1, ,b=2',  # whitespace-only segment
    ],
)
def test_malformed_pairs_are_rejected(raw):
    with pytest.raises(TagsHeaderMalformed) as err:
        parse_tags_header(raw)
    assert err.value.code == 'tags_header_malformed'
    assert err.value.status_code == 400


@pytest.mark.parametrize(
    'raw',
    [
        '_x=1',  # must start with a letter or digit
        '-x=1',
        '.x=1',
        'a b=1',  # space
        'a/b=1',  # disallowed character
        'x' * (MAX_TAG_KEY_LENGTH + 1) + '=1',
    ],
)
def test_invalid_keys_are_rejected(raw):
    with pytest.raises(TagsKeyInvalid) as err:
        parse_tags_header(raw)
    assert err.value.code == 'tags_key_invalid'


@pytest.mark.parametrize(
    'raw',
    [
        'k=' + 'v' * (MAX_TAG_VALUE_LENGTH + 1),
        'k=v=w',  # '=' is the key/value delimiter
        'k=va\x01ue',  # control character
        'k=café',  # non-ASCII
    ],
)
def test_invalid_values_are_rejected(raw):
    with pytest.raises(TagsValueInvalid) as err:
        parse_tags_header(raw)
    assert err.value.code == 'tags_value_invalid'


def test_key_cannot_contain_the_separator():
    """Split is on the first '=', so 'a=b=1' is key 'a' with an invalid value."""
    with pytest.raises(TagsValueInvalid):
        parse_tags_header('a=b=1')


def test_keys_and_values_at_their_length_limits_are_accepted():
    key = 'k' * MAX_TAG_KEY_LENGTH
    value = 'v' * MAX_TAG_VALUE_LENGTH
    assert parse_tags_header(f'{key}={value}') == (f'{key}={value}',)


def test_allowed_key_punctuation_is_accepted():
    assert parse_tags_header('a_b.c:d-e=1') == ('a_b.c:d-e=1',)


def test_error_names_the_offending_segment_and_its_position():
    with pytest.raises(TagsHeaderMalformed) as err:
        parse_tags_header('env=prod,broken,app=x')
    assert 'broken' in err.value.client_message
    assert 'tag 2' in err.value.client_message
    # log_message stays separate from what the client is told.
    assert 'broken' in err.value.log_message


def test_first_failure_left_to_right_is_reported():
    """Deterministic outcome: the same input always yields the same error."""
    with pytest.raises(TagsKeyInvalid):
        parse_tags_header('_bad=1,alsobad=' + 'v' * (MAX_TAG_VALUE_LENGTH + 1))
