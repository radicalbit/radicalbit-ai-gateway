import pytest

from radicalbit_ai_gateway.utils.content_utils import ContentUtils

HELLO_WORLD_BLOCKS = [
    {'type': 'text', 'text': 'Hello'},
    {'type': 'text', 'text': 'World'},
]


@pytest.mark.parametrize(
    ('content', 'strip', 'expected'),
    [
        pytest.param('hello world', False, 'hello world', id='string-as-is'),
        pytest.param('  hello world  ', True, 'hello world', id='string-stripped'),
        pytest.param(HELLO_WORLD_BLOCKS, False, 'Hello World', id='text-blocks-joined'),
        pytest.param(
            [
                {'type': 'text', 'text': 'Hello'},
                {'type': 'image', 'source_type': 'base64', 'data': 'abc123'},
                {'type': 'text', 'text': 'World'},
            ],
            False,
            'Hello World',
            id='non-text-blocks-ignored',
        ),
        pytest.param({'type': 'text', 'text': 'hello'}, False, 'hello', id='text-dict'),
        pytest.param(
            {'content': 'nested content'},
            False,
            'nested content',
            id='content-key-dict',
        ),
        pytest.param(b'hello world', False, 'hello world', id='bytes-utf8'),
        pytest.param(
            bytearray(b'hello world'), False, 'hello world', id='bytearray-utf8'
        ),
        pytest.param(None, False, '', id='none-empty'),
        pytest.param([], False, '', id='empty-list-empty'),
        pytest.param({}, False, '', id='empty-dict-empty'),
        pytest.param(
            [
                {'type': 'text', 'text': 'First'},
                [{'type': 'text', 'text': 'Nested'}],
                {'type': 'text', 'text': 'Last'},
            ],
            False,
            'First Nested Last',
            id='nested-list-recursive',
        ),
        pytest.param(
            [
                {'type': 'text', 'text': '  Hello  '},
                {'type': 'text', 'text': '  World  '},
            ],
            True,
            'Hello World',
            id='list-stripped',
        ),
        # The format produced by convert_openai_messages.
        pytest.param(
            [
                {'type': 'text', 'text': 'What is in this image?'},
                {'type': 'image', 'source_type': 'base64', 'data': 'base64data'},
            ],
            False,
            'What is in this image?',
            id='openai-multimodal',
        ),
    ],
)
def test_extract_text_content(content, strip, expected):
    assert ContentUtils.extract_text_content(content, strip=strip) == expected


@pytest.mark.parametrize(
    ('content', 'expected'),
    [
        pytest.param(None, None, id='none'),
        pytest.param('hello world', 'hello world', id='string-as-is'),
        pytest.param(HELLO_WORLD_BLOCKS, 'Hello World', id='blocks-joined'),
        pytest.param(
            '[{"type": "text", "text": "Hello"}, {"type": "text", "text": "World"}]',
            'Hello World',
            id='json-array-string-parsed',
        ),
        pytest.param(
            'Just a regular string', 'Just a regular string', id='non-json-string-as-is'
        ),
    ],
)
def test_normalize_openai_message_content(content, expected):
    assert ContentUtils.normalize_openai_message_content(content) == expected
