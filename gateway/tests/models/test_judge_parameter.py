from pydantic import ValidationError
import pytest

from radicalbit_ai_gateway.models.guardrails import JudgeParameter


def test_judge_parameter_accepts_prompt_ref():
    params = JudgeParameter(prompt_ref='toxicity_check.md', model_id='m1')
    assert params.prompt_ref == 'toxicity_check.md'
    assert params.prompt is None


def test_judge_parameter_accepts_inline_prompt():
    params = JudgeParameter(prompt='Flag any insult.', model_id='m1')
    assert params.prompt == 'Flag any insult.'
    assert params.prompt_ref is None


def test_judge_parameter_rejects_both_prompt_and_prompt_ref():
    with pytest.raises(
        ValidationError, match="Only one between 'prompt' and 'prompt_ref'"
    ):
        JudgeParameter(
            prompt='Flag any insult.', prompt_ref='toxicity_check.md', model_id='m1'
        )


@pytest.mark.parametrize(
    ('prompt', 'prompt_ref'), [(None, None), ('  ', None), (None, '')]
)
def test_judge_parameter_requires_prompt_or_prompt_ref(prompt, prompt_ref):
    with pytest.raises(ValidationError, match="One between 'prompt' and 'prompt_ref'"):
        JudgeParameter(prompt=prompt, prompt_ref=prompt_ref, model_id='m1')


def test_judge_parameter_rejects_missing_prompt_file():
    with pytest.raises(
        ValidationError, match='Prompt file not found: non_existent_prompt.md'
    ):
        JudgeParameter(prompt_ref='non_existent_prompt.md', model_id='m1')
