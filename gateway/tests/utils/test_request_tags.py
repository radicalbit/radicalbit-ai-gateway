import pytest

from radicalbit_ai_gateway.utils.exceptions import TagsHeaderError
from radicalbit_ai_gateway.utils.request_tags import (
    MAX_TAG_KEY_LENGTH,
    MAX_TAG_VALUE_LENGTH,
    MAX_TAGS_HEADER_BYTES,
    parse_tags_header,
)


def test_parses_the_documented_example():
    assert parse_tags_header('cost_center=retail,env=prod,app=my-app') == (
        'app=my-app',
        'cost_center=retail',
        'env=prod',
    )


@pytest.mark.parametrize('raw', [None, '', '   ', '\t'])
def test_absent_or_blank_header_yields_no_tags(raw):
    assert parse_tags_header(raw) == ()


def test_result_is_independent_of_header_order():
    assert parse_tags_header('env=prod,app=x,cost_center=retail') == parse_tags_header(
        'cost_center=retail,env=prod,app=x'
    )


def test_same_key_with_different_values_keeps_both():
    assert parse_tags_header('env=prod,env=staging') == ('env=prod', 'env=staging')


def test_identical_pairs_are_deduplicated():
    assert parse_tags_header('env=prod,env=prod,env=staging') == (
        'env=prod',
        'env=staging',
    )


def test_whitespace_around_pairs_and_separator_is_trimmed():
    assert parse_tags_header('  env = prod , app=x ') == ('app=x', 'env=prod')


def test_a_header_at_exactly_the_byte_limit_is_accepted():
    raw = ','.join(['k=' + 'v' * 14] * 241)  # 4096 bytes on the nose
    assert len(raw.encode('utf-8')) == MAX_TAGS_HEADER_BYTES
    assert parse_tags_header(raw) == ('k=' + 'v' * 14,)


def test_oversized_header_is_rejected():
    raw = 'a=1,' * 2000
    with pytest.raises(TagsHeaderError) as err:
        parse_tags_header(raw)
    assert err.value.code == 'tags_header_too_large'
    assert err.value.status_code == 400
    assert str(MAX_TAGS_HEADER_BYTES) in err.value.client_message


def test_size_limit_counts_bytes_not_characters():
    raw = 'k=' + 'é' * MAX_TAGS_HEADER_BYTES
    with pytest.raises(TagsHeaderError):
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
    with pytest.raises(TagsHeaderError) as err:
        parse_tags_header(raw)
    assert err.value.code == 'tags_header_invalid'
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
    with pytest.raises(TagsHeaderError) as err:
        parse_tags_header(raw)
    assert err.value.code == 'tags_header_invalid'


@pytest.mark.parametrize(
    'raw',
    [
        'k=' + 'v' * (MAX_TAG_VALUE_LENGTH + 1),
        'k=v=w',  # '=' is the key/value delimiter
        'k=va\x01ue',  # control character
        'k=café',  # non-ASCII
        'k=va lue',  # space
        'k=va,lue',  # ',' is the pair separator
        'k=va!lue',  # disallowed symbol
        'k=va;lue',  # disallowed symbol
        'k=va&lue',  # disallowed symbol
        'k=va"lue',  # disallowed symbol
    ],
)
def test_invalid_values_are_rejected(raw):
    with pytest.raises(TagsHeaderError) as err:
        parse_tags_header(raw)
    assert err.value.code == 'tags_header_invalid'


def test_keys_and_values_at_their_length_limits_are_accepted():
    key = 'k' * MAX_TAG_KEY_LENGTH
    value = 'v' * MAX_TAG_VALUE_LENGTH
    assert parse_tags_header(f'{key}={value}') == (f'{key}={value}',)


def test_allowed_key_punctuation_is_accepted():
    assert parse_tags_header('a_b.c:d-e=1') == ('a_b.c:d-e=1',)


def test_allowed_value_punctuation_is_accepted():
    assert parse_tags_header('k=a_b.c:d-e/f+h@i#j') == ('k=a_b.c:d-e/f+h@i#j',)


def test_error_names_the_offending_segment_and_its_position():
    with pytest.raises(TagsHeaderError) as err:
        parse_tags_header('env=prod,broken,app=x')
    assert 'broken' in err.value.client_message
    assert 'tag 2' in err.value.client_message
