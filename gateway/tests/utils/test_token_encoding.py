import tiktoken

from radicalbit_ai_gateway.utils.token_encoding import (
    DEFAULT_ENCODING,
    DeepSeekEncodingAdapter,
    TiktokenEncodingAdapter,
    TokenEncoding,
    get_encoding_for_model,
)


class TestGetEncodingForModel:
    @staticmethod
    def setup_method():
        get_encoding_for_model.cache_clear()

    def test_openai_returns_tiktoken_adapter(self):
        enc = get_encoding_for_model('openai/gpt-4o')
        assert isinstance(enc, TiktokenEncodingAdapter)

    def test_openai_gpt4o_returns_o200k_base(self):
        enc = get_encoding_for_model('openai/gpt-4o')
        assert enc.name == 'o200k_base'

    def test_openai_gpt4_returns_cl100k_base(self):
        enc = get_encoding_for_model('openai/gpt-4')
        assert enc.name == 'cl100k_base'

    def test_openai_gpt35_turbo_returns_cl100k_base(self):
        enc = get_encoding_for_model('openai/gpt-3.5-turbo')
        assert enc.name == 'cl100k_base'

    def test_openai_gpt4o_mini_returns_o200k_base(self):
        enc = get_encoding_for_model('openai/gpt-4o-mini')
        assert enc.name == 'o200k_base'

    def test_azure_model_uses_encoding_for_model(self):
        enc = get_encoding_for_model('azure/gpt-4')
        assert enc.name == 'cl100k_base'

    def test_unknown_openai_model_falls_back_to_default(self):
        enc = get_encoding_for_model('openai/some-unknown-model-xyz')
        assert enc.name == DEFAULT_ENCODING

    def test_anthropic_returns_default(self):
        enc = get_encoding_for_model('anthropic/claude-3-5-sonnet-latest')
        assert enc.name == DEFAULT_ENCODING

    def test_deepseek_returns_deepseek_adapter(self):
        enc = get_encoding_for_model('deepseek/deepseek-chat')
        assert isinstance(enc, DeepSeekEncodingAdapter)
        assert enc.name == 'deepseek'

    def test_deepseek_produces_tokens(self):
        enc = get_encoding_for_model('deepseek/deepseek-chat')
        tokens = enc.encode('Hello, world!')
        assert len(tokens) > 0

    def test_deepseek_token_count_differs_from_cl100k(self):
        text = 'The quick brown fox jumps over the lazy dog. 你好世界'
        ds_enc = get_encoding_for_model('deepseek/deepseek-chat')
        cl_enc = tiktoken.get_encoding(DEFAULT_ENCODING)
        ds_tokens = len(ds_enc.encode(text))
        cl_tokens = len(cl_enc.encode(text))
        assert ds_tokens != cl_tokens

    def test_deepseek_satisfies_protocol(self):
        enc = get_encoding_for_model('deepseek/deepseek-chat')
        assert isinstance(enc, TokenEncoding)

    def test_google_genai_returns_default(self):
        enc = get_encoding_for_model('google-genai/gemini-1.5-pro')
        assert enc.name == DEFAULT_ENCODING

    def test_ollama_via_openai_provider(self):
        """Ollama models using openai/ prefix with custom base_url should
        fall back to default when tiktoken doesn't know the model name.
        """
        enc = get_encoding_for_model('openai/llama3')
        assert enc.name == DEFAULT_ENCODING

    def test_mock_provider_returns_default(self):
        enc = get_encoding_for_model('mock/test-model')
        assert enc.name == DEFAULT_ENCODING

    def test_empty_string_returns_default(self):
        enc = get_encoding_for_model('')
        assert enc.name == DEFAULT_ENCODING

    def test_no_slash_returns_default(self):
        enc = get_encoding_for_model('gpt-4o')
        assert enc.name == DEFAULT_ENCODING

    def test_encoding_produces_tokens(self):
        enc = get_encoding_for_model('openai/gpt-4o')
        tokens = enc.encode('Hello, world!')
        assert len(tokens) > 0

    def test_results_are_cached(self):
        enc1 = get_encoding_for_model('openai/gpt-4')
        enc2 = get_encoding_for_model('openai/gpt-4')
        assert enc1 is enc2
