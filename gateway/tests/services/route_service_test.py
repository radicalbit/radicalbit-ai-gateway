import copy
import unittest

from tests.common.mocked_gateway_config import get_default_gateway

from radicalbit_ai_gateway.models.guardrails import (
    Guardrail,
    GuardrailType,
    JudgeParameter,
)
from radicalbit_ai_gateway.models.prompt_dto import PromptCategory
from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.routes.dashboard_route import _get_route_prompts
from radicalbit_ai_gateway.utils.app_config import PromptManagerConfig


class RouteServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateway_config = get_default_gateway('route-A')

    def test_get_route_prompts_no_prompts(self):
        """All models have prompt=None, so tokens should be 0 for each."""
        result = _get_route_prompts('route-A', self.gateway_config)
        assert result.route_name == 'route-A'
        assert len(result.prompts) == 3
        for item in result.prompts:
            assert item.category == PromptCategory.CHAT_MODEL
            assert item.prompt is None
            assert item.tokens == 0

    def test_get_route_prompts_with_prompt(self):
        """Model with an inline prompt should return prompt text and tokens > 0."""
        config = copy.deepcopy(self.gateway_config)
        model = config.chat_models_by_id['openai']
        object.__setattr__(model, 'prompt', 'You are a helpful assistant.')
        result = _get_route_prompts('route-A', config)
        openai_item = next(p for p in result.prompts if p.model_id == 'openai')
        assert openai_item.prompt == 'You are a helpful assistant.'
        assert openai_item.tokens > 0
        assert openai_item.model_name == 'openai/gpt-4o'

    def test_get_route_prompts_model_ids_order(self):
        """Prompt items should follow the order of chat_models in the route config."""
        result = _get_route_prompts('route-A', self.gateway_config)
        model_ids = [p.model_id for p in result.prompts]
        assert model_ids == ['openai', 'azure', 'deepseek']

    def test_get_route_prompts_excludes_non_judge_guardrails(self):
        """Non-JUDGE guardrails should not appear in the prompts list."""
        result = _get_route_prompts('route-A', self.gateway_config)
        judge_items = [
            p for p in result.prompts if p.category == PromptCategory.GUARDRAIL_JUDGE
        ]
        assert len(judge_items) == 0

    def test_get_route_prompts_with_judge_guardrail(self):
        """JUDGE guardrail should produce a guardrail-judge item with resolved prompt."""
        pm = PromptManager(conf=PromptManagerConfig())
        PromptManager.set_global(pm)

        config = copy.deepcopy(self.gateway_config)
        judge = Guardrail(
            name='injection_check',
            type=GuardrailType.JUDGE,
            where='INPUT',
            behavior='BLOCK',
            parameters=JudgeParameter(
                prompt_ref='prompt_injection_check.md',
                model_id='openai',
            ),
        )
        config.guardrails.append(judge)
        config.routes['route-A'].guardrails.append('injection_check')

        result = _get_route_prompts('route-A', config)

        judge_items = [
            p for p in result.prompts if p.category == PromptCategory.GUARDRAIL_JUDGE
        ]
        assert len(judge_items) == 1
        assert judge_items[0].guardrail_name == 'injection_check'
        assert judge_items[0].model_id == 'openai'
        assert judge_items[0].model_name == 'openai/gpt-4o'
        assert judge_items[0].prompt is not None
        assert judge_items[0].tokens > 0

        PromptManager._global_instance = None

    def test_get_route_prompts_judge_prompt_not_found(self):
        """Missing judge prompt file should result in prompt=None and tokens=0."""
        pm = PromptManager(conf=PromptManagerConfig())
        PromptManager.set_global(pm)

        config = copy.deepcopy(self.gateway_config)
        judge = Guardrail(
            name='missing_prompt',
            type=GuardrailType.JUDGE,
            where='INPUT',
            behavior='BLOCK',
            parameters=JudgeParameter(
                prompt_ref='non_existent_prompt.md',
                model_id='openai',
            ),
        )
        config.guardrails.append(judge)
        config.routes['route-A'].guardrails.append('missing_prompt')

        result = _get_route_prompts('route-A', config)

        judge_items = [
            p for p in result.prompts if p.category == PromptCategory.GUARDRAIL_JUDGE
        ]
        assert len(judge_items) == 1
        assert judge_items[0].prompt is None
        assert judge_items[0].tokens == 0

        PromptManager._global_instance = None
