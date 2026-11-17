import pytest

from radicalbit_ai_gateway.utils.exceptions import TagsHeaderError
from radicalbit_ai_gateway.utils.request_tags import (
    MAX_TAG_KEY_LENGTH,
    MAX_TAG_VALUE_LENGTH,
    MAX_TAGS_HEADER_BYTES,
    parse_tags_header,
)


@pytest.mark.parametrize('raw', [None, '', '   ', '\t'])
def test_absent_or_blank_header_yields_no_tags(raw):
    assert parse_tags_header(raw) == ()


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        pytest.param(
            'cost_center=retail,env=prod,app=my-app',
            ('app=my-app', 'cost_center=retail', 'env=prod'),
            id='documented-example-sorted',
        ),
        pytest.param(
            'env=prod,env=staging',
            ('env=prod', 'env=staging'),
            id='same-key-different-values-kept',
        ),
        pytest.param(
            'env=prod,env=prod,env=staging',
            ('env=prod', 'env=staging'),
            id='identical-pairs-deduplicated',
        ),
        pytest.param(
            '  env = prod , app=x ', ('app=x', 'env=prod'), id='whitespace-trimmed'
        ),
        pytest.param(
            f'{"k" * MAX_TAG_KEY_LENGTH}={"v" * MAX_TAG_VALUE_LENGTH}',
            (f'{"k" * MAX_TAG_KEY_LENGTH}={"v" * MAX_TAG_VALUE_LENGTH}',),
            id='key-and-value-at-length-limits',
        ),
        pytest.param('a_b.c:d-e=1', ('a_b.c:d-e=1',), id='allowed-key-punctuation'),
        pytest.param(
            'k=a_b.c:d-e/f+h@i#j',
            ('k=a_b.c:d-e/f+h@i#j',),
            id='allowed-value-punctuation',
        ),
    ],
)
def test_valid_tags_are_parsed(raw, expected):
    assert parse_tags_header(raw) == expected


def test_result_is_independent_of_header_order():
    assert parse_tags_header('env=prod,app=x,cost_center=retail') == parse_tags_header(
        'cost_center=retail,env=prod,app=x'
    )


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
        # malformed pairs
        pytest.param('env', id='no-equals'),
        pytest.param('=prod', id='empty-key'),
        pytest.param('env=', id='empty-value'),
        pytest.param('a=1,,b=2', id='empty-segment'),
        pytest.param('a=1,', id='trailing-comma'),
        pytest.param(',a=1', id='leading-comma'),
        pytest.param('a=1, ,b=2', id='whitespace-only-segment'),
        # invalid keys: must start with a letter or digit
        pytest.param('_x=1', id='key-starts-with-underscore'),
        pytest.param('-x=1', id='key-starts-with-dash'),
        pytest.param('.x=1', id='key-starts-with-dot'),
        pytest.param('a b=1', id='key-with-space'),
        pytest.param('a/b=1', id='key-with-slash'),
        pytest.param('x' * (MAX_TAG_KEY_LENGTH + 1) + '=1', id='key-too-long'),
        # invalid values
        pytest.param('k=' + 'v' * (MAX_TAG_VALUE_LENGTH + 1), id='value-too-long'),
        pytest.param('k=v=w', id='value-with-equals'),
        pytest.param('k=va\x01ue', id='value-control-character'),
        pytest.param('k=café', id='value-non-ascii'),
        pytest.param('k=va lue', id='value-with-space'),
        pytest.param('k=va,lue', id='value-with-comma'),
        pytest.param('k=va!lue', id='value-with-bang'),
        pytest.param('k=va;lue', id='value-with-semicolon'),
        pytest.param('k=va&lue', id='value-with-ampersand'),
        pytest.param('k=va"lue', id='value-with-quote'),
    ],
)
def test_invalid_tags_are_rejected(raw):
    with pytest.raises(TagsHeaderError) as err:
        parse_tags_header(raw)
    assert err.value.code == 'tags_header_invalid'
    assert err.value.status_code == 400


def test_error_names_the_offending_segment_and_its_position():
    with pytest.raises(TagsHeaderError) as err:
        parse_tags_header('env=prod,broken,app=x')
    assert 'broken' in err.value.client_message
    assert 'tag 2' in err.value.client_message
