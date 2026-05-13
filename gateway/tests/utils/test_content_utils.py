from radicalbit_ai_gateway.utils.content_utils import ContentUtils


class TestContentUtilsExtractTextContent:
    """Test suite for ContentUtils.extract_text_content method."""

    def test_extract_simple_string(self):
        """Simple string is returned as-is."""
        assert ContentUtils.extract_text_content('hello world') == 'hello world'

    def test_extract_simple_string_with_strip(self):
        """String is stripped when strip=True."""
        assert (
            ContentUtils.extract_text_content('  hello world  ', strip=True)
            == 'hello world'
        )

    def test_extract_from_list_of_text_blocks(self):
        """List of text blocks is concatenated with spaces."""
        content = [
            {'type': 'text', 'text': 'Hello'},
            {'type': 'text', 'text': 'World'},
        ]
        assert ContentUtils.extract_text_content(content) == 'Hello World'

    def test_extract_from_list_ignores_non_text_blocks(self):
        """Non-text blocks (like images) are ignored."""
        content = [
            {'type': 'text', 'text': 'Hello'},
            {'type': 'image', 'source_type': 'base64', 'data': 'abc123'},
            {'type': 'text', 'text': 'World'},
        ]
        assert ContentUtils.extract_text_content(content) == 'Hello World'

    def test_extract_from_dict_with_type_text(self):
        """Dict with type='text' returns text value."""
        content = {'type': 'text', 'text': 'hello'}
        assert ContentUtils.extract_text_content(content) == 'hello'

    def test_extract_from_dict_with_content_key(self):
        """Dict with 'content' key returns that value."""
        content = {'content': 'nested content'}
        assert ContentUtils.extract_text_content(content) == 'nested content'

    def test_extract_from_bytes(self):
        """Bytes are decoded as UTF-8."""
        content = b'hello world'
        assert ContentUtils.extract_text_content(content) == 'hello world'

    def test_extract_from_bytearray(self):
        """Bytearray is decoded as UTF-8."""
        content = bytearray(b'hello world')
        assert ContentUtils.extract_text_content(content) == 'hello world'

    def test_extract_none_returns_empty(self):
        """None returns empty string."""
        assert ContentUtils.extract_text_content(None) == ''

    def test_extract_empty_list_returns_empty(self):
        """Empty list returns empty string."""
        assert ContentUtils.extract_text_content([]) == ''

    def test_extract_empty_dict_returns_empty(self):
        """Empty dict returns empty string."""
        assert ContentUtils.extract_text_content({}) == ''

    def test_extract_nested_list_structure(self):
        """Nested structures are handled recursively."""
        content = [
            {'type': 'text', 'text': 'First'},
            [{'type': 'text', 'text': 'Nested'}],
            {'type': 'text', 'text': 'Last'},
        ]
        assert ContentUtils.extract_text_content(content) == 'First Nested Last'

    def test_extract_with_strip_on_list(self):
        """Strip option works on list content."""
        content = [
            {'type': 'text', 'text': '  Hello  '},
            {'type': 'text', 'text': '  World  '},
        ]
        assert ContentUtils.extract_text_content(content, strip=True) == 'Hello World'

    def test_extract_openai_multimodal_format(self):
        """OpenAI multimodal message format is handled correctly."""
        # This is the format used after convert_openai_messages
        content = [
            {'type': 'text', 'text': 'What is in this image?'},
            {'type': 'image', 'source_type': 'base64', 'data': 'base64data'},
        ]
        assert ContentUtils.extract_text_content(content) == 'What is in this image?'


class TestContentUtilsNormalizeOpenaiMessageContent:
    """Test suite for ContentUtils.normalize_openai_message_content method."""

    def test_normalize_none_returns_none(self):
        """None input returns None."""
        assert ContentUtils.normalize_openai_message_content(None) is None

    def test_normalize_simple_string(self):
        """Simple string is returned as-is."""
        assert (
            ContentUtils.normalize_openai_message_content('hello world')
            == 'hello world'
        )

    def test_normalize_list_of_blocks(self):
        """List of blocks is joined into a string."""
        content = [
            {'type': 'text', 'text': 'Hello'},
            {'type': 'text', 'text': 'World'},
        ]
        assert ContentUtils.normalize_openai_message_content(content) == 'Hello World'

    def test_normalize_json_string_array(self):
        """JSON string containing array is parsed and normalized."""
        content = (
            '[{"type": "text", "text": "Hello"}, {"type": "text", "text": "World"}]'
        )
        assert ContentUtils.normalize_openai_message_content(content) == 'Hello World'

    def test_normalize_non_json_string_unchanged(self):
        """Non-JSON string is returned as-is."""
        content = 'Just a regular string'
        assert (
            ContentUtils.normalize_openai_message_content(content)
            == 'Just a regular string'
        )
