from pydantic import ValidationError
import pytest

from radicalbit_ai_gateway.models.guardrails import JudgeParameter


@pytest.mark.parametrize(
    ('prompt', 'prompt_ref'),
    [
        pytest.param(None, 'toxicity_check.md', id='prompt-ref'),
        pytest.param('Flag any insult.', None, id='inline-prompt'),
    ],
)
def test_judge_parameter_accepts_one_prompt_source(prompt, prompt_ref):
    params = JudgeParameter(prompt=prompt, prompt_ref=prompt_ref, model_id='m1')
    assert (params.prompt, params.prompt_ref) == (prompt, prompt_ref)


@pytest.mark.parametrize(
    ('prompt', 'prompt_ref', 'match'),
    [
        pytest.param(
            'Flag any insult.',
            'toxicity_check.md',
            "Only one between 'prompt' and 'prompt_ref'",
            id='both-set',
        ),
        pytest.param(
            None, None, "One between 'prompt' and 'prompt_ref'", id='neither-set'
        ),
        pytest.param(
            '  ', None, "One between 'prompt' and 'prompt_ref'", id='blank-prompt'
        ),
        pytest.param(
            None, '', "One between 'prompt' and 'prompt_ref'", id='empty-prompt-ref'
        ),
        pytest.param(
            None,
            'non_existent_prompt.md',
            'Prompt file not found: non_existent_prompt.md',
            id='missing-prompt-file',
        ),
    ],
)
def test_judge_parameter_rejects_invalid_prompt_source(prompt, prompt_ref, match):
    with pytest.raises(ValidationError, match=match):
        JudgeParameter(prompt=prompt, prompt_ref=prompt_ref, model_id='m1')
