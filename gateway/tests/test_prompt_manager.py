from __future__ import annotations

from pathlib import Path

import pytest

from radicalbit_ai_gateway.prompt_manager import PromptManager
from radicalbit_ai_gateway.utils.app_config import PromptManagerConfig


class TestPromptManager:
    def teardown_method(self):
        PromptManager._global_instance = None

    def test_creates_optional_dirs_when_configured(self, tmp_path: Path):
        model_dir = tmp_path / 'model_prompts'
        judge_custom_dir = tmp_path / 'judge_custom_prompts'

        conf = PromptManagerConfig(
            prompts_dir=str(model_dir),
            judge_prompts_dir=str(judge_custom_dir),
        )

        _ = PromptManager(conf=conf)

        assert model_dir.exists() and model_dir.is_dir()
        assert judge_custom_dir.exists() and judge_custom_dir.is_dir()

    def test_does_not_create_optional_dirs_when_not_configured(self, tmp_path: Path):
        model_dir = tmp_path / 'model_prompts'
        judge_custom_dir = tmp_path / 'judge_custom_prompts'

        conf = PromptManagerConfig(prompts_dir=None, judge_prompts_dir=None)

        _ = PromptManager(conf=conf)

        assert not model_dir.exists()
        assert not judge_custom_dir.exists()

    def test_get_model_prompt_raises_if_model_dir_not_configured(self):
        conf = PromptManagerConfig(prompts_dir=None, judge_prompts_dir=None)
        pm = PromptManager(conf=conf)

        with pytest.raises(ValueError, match='Model prompts directory not configured'):
            pm.get_model_prompt('any.md')

    def test_get_model_prompt_reads_from_configured_dir(self, tmp_path: Path):
        model_dir = tmp_path / 'model_prompts'
        model_dir.mkdir(parents=True, exist_ok=True)

        md = model_dir / 'jamie.md'
        md.write_text('# Hello\nYou are Jamie.', encoding='utf-8')

        conf = PromptManagerConfig(prompts_dir=str(model_dir), judge_prompts_dir=None)
        pm = PromptManager(conf=conf)

        content = pm.get_model_prompt('jamie.md')
        assert 'You are Jamie.' in content

    def test_get_judge_prompt_reads_from_custom_dir_when_configured(
        self, tmp_path: Path
    ):
        judge_custom_dir = tmp_path / 'judge_custom_prompts'
        judge_custom_dir.mkdir(parents=True, exist_ok=True)

        md = judge_custom_dir / 'business_context_check.md'
        md.write_text('You are a business context judge.', encoding='utf-8')

        conf = PromptManagerConfig(
            prompts_dir=None, judge_prompts_dir=str(judge_custom_dir)
        )
        pm = PromptManager(conf=conf)

        content = pm.get_judge_prompt('business_context_check.md')
        assert content == 'You are a business context judge.'
