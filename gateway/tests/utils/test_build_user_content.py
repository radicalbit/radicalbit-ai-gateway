import pytest

from radicalbit_ai_gateway.utils.build_user_content import (
    _stable_json_dumps,
    build_user_content,
    stringify_message_content,
)


class FakeMessage:
    """Minimal stand-in for langchain_core.messages.BaseMessage for these tests."""

    def __init__(self, content):
        self.content = content


class _Weird:
    def __str__(self):
        return '  WEIRD  '


@pytest.mark.parametrize(
    ('contents', 'expected'),
    [
        pytest.param([], '', id='empty-list'),
        pytest.param(['Hello', 'world'], 'Hello world', id='only-text'),
        # "" is skipped but "   " is truthy and kept; the final strip only
        # normalises the ends, not the middle.
        pytest.param(
            ['Hello', '   ', 'world', ''], 'Hello     world', id='empty-and-whitespace'
        ),
        pytest.param(
            [
                [
                    {'type': 'text', 'text': 'A'},
                    {'type': 'image_url', 'image_url': {'url': 'https://x/y.png'}},
                ],
                'B',
                [{'type': 'text', 'text': 'C'}],
            ],
            'A https://x/y.png B C',
            id='multimodal-joined-with-spaces',
        ),
    ],
)
def test_build_user_content(contents, expected):
    assert build_user_content([FakeMessage(c) for c in contents]) == expected


@pytest.mark.parametrize(
    ('content', 'expected'),
    [
        pytest.param('Hello!', 'Hello!', id='str-as-is'),
        pytest.param(
            [
                {'type': 'text', 'text': "What's in this image?"},
                {'type': 'text', 'text': 'Second line'},
            ],
            "What's in this image? Second line",
            id='text-blocks',
        ),
        pytest.param(
            [
                {'type': 'text', 'text': "What's in this image?"},
                {
                    'type': 'image_url',
                    'image_url': {'url': 'https://example.com/image.jpg'},
                },
            ],
            "What's in this image? https://example.com/image.jpg",
            id='image-url-block-includes-url',
        ),
        # Deterministic JSON dump: keys sorted, compact separators.
        pytest.param(
            [{'type': 'image_url', 'image_url': {'not_url': 'x'}}],
            _stable_json_dumps({'type': 'image_url', 'image_url': {'not_url': 'x'}}),
            id='image-url-without-url-falls-back-to-json',
        ),
        pytest.param(
            [
                {
                    'type': 'input_audio',
                    'audio': {'format': 'wav', 'data': '...'},
                    'x': 1,
                }
            ],
            _stable_json_dumps(
                {
                    'type': 'input_audio',
                    'audio': {'format': 'wav', 'data': '...'},
                    'x': 1,
                }
            ),
            id='unknown-dict-type-falls-back-to-json',
        ),
        pytest.param(
            [
                'prefix',
                {'type': 'text', 'text': 'hello'},
                123,  # not expected by type, but handled
                {
                    'type': 'image_url',
                    'image_url': {'url': 'https://example.com/a.png'},
                },
                {'foo': 'bar'},  # unknown dict type -> json
            ],
            'prefix hello 123 https://example.com/a.png '
            + _stable_json_dumps({'foo': 'bar'}),
            id='mixed-list',
        ),
        # The final fallback: str(content).strip().
        pytest.param(_Weird(), 'WEIRD', id='unexpected-type-str'),
    ],
)
def test_stringify_message_content(content, expected):
    assert stringify_message_content(content) == expected


def test_stable_json_dumps_is_deterministic_key_order():
    obj = {'b': 2, 'a': 1, 'nested': {'z': 0, 'y': 1}}
    assert _stable_json_dumps(obj) == '{"a":1,"b":2,"nested":{"y":1,"z":0}}'
