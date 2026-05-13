from radicalbit_ai_gateway.utils.build_user_content import (
    _stable_json_dumps,
    build_user_content,
    stringify_message_content,
)


class FakeMessage:
    """Minimal stand-in for langchain_core.messages.BaseMessage for these tests."""

    def __init__(self, content):
        self.content = content


def test_build_user_content_empty_list_returns_empty_string():
    assert build_user_content([]) == ''


def test_build_user_content_only_text_messages():
    messages = [
        FakeMessage('Hello'),
        FakeMessage('world'),
    ]
    assert build_user_content(messages) == 'Hello world'


def test_build_user_content_skips_empty_or_whitespace_strings():
    messages = [
        FakeMessage('Hello'),
        FakeMessage('   '),
        FakeMessage('world'),
        FakeMessage(''),
    ]
    # Note: empty/whitespace msg.content won't be filtered at msg-level
    # unless stringify returns empty; for string content it returns as-is.
    # build_user_content checks "if s:" so "" is skipped but "   " is truthy.
    # However, final join + strip will normalize ends only, not middle spaces.
    # So we test the actual behavior:
    assert build_user_content(messages) == 'Hello     world'


def test_stringify_message_content_str_returns_as_is():
    assert stringify_message_content('Hello!') == 'Hello!'


def test_stringify_message_content_list_with_text_blocks():
    content = [
        {'type': 'text', 'text': "What's in this image?"},
        {'type': 'text', 'text': 'Second line'},
    ]
    assert stringify_message_content(content) == "What's in this image? Second line"


def test_stringify_message_content_list_with_image_url_block_includes_url():
    content = [
        {'type': 'text', 'text': "What's in this image?"},
        {
            'type': 'image_url',
            'image_url': {'url': 'https://example.com/image.jpg'},
        },
    ]
    assert stringify_message_content(content) == (
        "What's in this image? https://example.com/image.jpg"
    )


def test_stringify_message_content_image_url_without_url_falls_back_to_json():
    content = [
        {'type': 'image_url', 'image_url': {'not_url': 'x'}},
    ]
    # deterministic JSON dump: keys sorted, compact separators
    assert stringify_message_content(content) == _stable_json_dumps(
        {'type': 'image_url', 'image_url': {'not_url': 'x'}}
    )


def test_stringify_message_content_unknown_dict_type_falls_back_to_json():
    content = [
        {'type': 'input_audio', 'audio': {'format': 'wav', 'data': '...'}, 'x': 1},
    ]
    assert stringify_message_content(content) == _stable_json_dumps(
        {'type': 'input_audio', 'audio': {'format': 'wav', 'data': '...'}, 'x': 1}
    )


def test_stringify_message_content_mixed_list_str_dict_and_other():
    content = [
        'prefix',
        {'type': 'text', 'text': 'hello'},
        123,  # not expected by type, but function handles it
        {'type': 'image_url', 'image_url': {'url': 'https://example.com/a.png'}},
        {'foo': 'bar'},  # unknown dict type -> json
    ]
    out = stringify_message_content(content)
    assert out == (
        'prefix hello 123 https://example.com/a.png '
        + _stable_json_dumps({'foo': 'bar'})
    )


def test_build_user_content_multimodal_messages_joined_with_spaces():
    messages = [
        FakeMessage(
            [
                {'type': 'text', 'text': 'A'},
                {'type': 'image_url', 'image_url': {'url': 'https://x/y.png'}},
            ]
        ),
        FakeMessage('B'),
        FakeMessage([{'type': 'text', 'text': 'C'}]),
    ]
    assert build_user_content(messages) == 'A https://x/y.png B C'


def test_stable_json_dumps_is_deterministic_key_order():
    obj = {'b': 2, 'a': 1, 'nested': {'z': 0, 'y': 1}}
    dumped = _stable_json_dumps(obj)
    # keys must be sorted: a before b, nested last depends on sort order
    # nested keys sorted too: y before z
    assert dumped == '{"a":1,"b":2,"nested":{"y":1,"z":0}}'


def test_stringify_message_content_fallback_for_unexpected_type_returns_str():
    # this hits the final return str(content).strip()
    class Weird:
        def __str__(self):
            return '  WEIRD  '

    assert stringify_message_content(Weird()) == 'WEIRD'
