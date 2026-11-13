import pytest
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

    @pytest.mark.parametrize(
        ('model', 'adapter', 'name'),
        [
            pytest.param(
                'openai/gpt-4o',
                TiktokenEncodingAdapter,
                'o200k_base',
                id='openai-gpt-4o',
            ),
            pytest.param(
                'openai/gpt-4o-mini',
                TiktokenEncodingAdapter,
                'o200k_base',
                id='openai-gpt-4o-mini',
            ),
            pytest.param(
                'openai/gpt-4',
                TiktokenEncodingAdapter,
                'cl100k_base',
                id='openai-gpt-4',
            ),
            pytest.param(
                'openai/gpt-3.5-turbo',
                TiktokenEncodingAdapter,
                'cl100k_base',
                id='openai-gpt-3.5-turbo',
            ),
            pytest.param(
                'azure/gpt-4',
                TiktokenEncodingAdapter,
                'cl100k_base',
                id='azure-uses-encoding-for-model',
            ),
            pytest.param(
                'openai/some-unknown-model-xyz',
                TiktokenEncodingAdapter,
                DEFAULT_ENCODING,
                id='unknown-openai-model-default',
            ),
            # Ollama models behind the openai/ prefix are unknown to tiktoken.
            pytest.param(
                'openai/llama3',
                TiktokenEncodingAdapter,
                DEFAULT_ENCODING,
                id='ollama-via-openai-default',
            ),
            pytest.param(
                'anthropic/claude-3-5-sonnet-latest',
                TiktokenEncodingAdapter,
                DEFAULT_ENCODING,
                id='anthropic-default',
            ),
            pytest.param(
                'google-genai/gemini-1.5-pro',
                TiktokenEncodingAdapter,
                DEFAULT_ENCODING,
                id='google-genai-default',
            ),
            pytest.param(
                'mock/test-model',
                TiktokenEncodingAdapter,
                DEFAULT_ENCODING,
                id='mock-default',
            ),
            pytest.param(
                '', TiktokenEncodingAdapter, DEFAULT_ENCODING, id='empty-string-default'
            ),
            pytest.param(
                'gpt-4o',
                TiktokenEncodingAdapter,
                DEFAULT_ENCODING,
                id='no-slash-default',
            ),
            pytest.param(
                'deepseek/deepseek-chat',
                DeepSeekEncodingAdapter,
                'deepseek',
                id='deepseek',
            ),
        ],
    )
    def test_selects_the_encoding_for_the_model(self, model, adapter, name):
        enc = get_encoding_for_model(model)
        assert isinstance(enc, adapter)
        assert isinstance(enc, TokenEncoding)
        assert enc.name == name

    @pytest.mark.parametrize(
        'model',
        [
            pytest.param('openai/gpt-4o', id='tiktoken'),
            pytest.param('deepseek/deepseek-chat', id='deepseek'),
        ],
    )
    def test_encoding_produces_tokens(self, model):
        tokens = get_encoding_for_model(model).encode('Hello, world!')
        assert len(tokens) > 0

    def test_deepseek_token_count_differs_from_cl100k(self):
        text = 'The quick brown fox jumps over the lazy dog. 你好世界'
        ds_enc = get_encoding_for_model('deepseek/deepseek-chat')
        cl_enc = tiktoken.get_encoding(DEFAULT_ENCODING)
        ds_tokens = len(ds_enc.encode(text))
        cl_tokens = len(cl_enc.encode(text))
        assert ds_tokens != cl_tokens

    def test_results_are_cached(self):
        enc1 = get_encoding_for_model('openai/gpt-4')
        enc2 = get_encoding_for_model('openai/gpt-4')
        assert enc1 is enc2
