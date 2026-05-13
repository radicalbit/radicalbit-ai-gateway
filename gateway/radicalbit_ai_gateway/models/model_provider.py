from enum import Enum


class ModelProvider(str, Enum):
    OPENAI = 'openai'
    AZURE = 'azure'
    DEEPSEEK = 'deepseek'
    OLLAMA = 'ollama'
    VLLM = 'vllm'
    # ANTHROPIC = 'anthropic'
