"""A judge's structured answer: its result, or why it could not be read."""

import pytest

from radicalbit_ai_gateway.llm.messages import AIMessage
from radicalbit_ai_gateway.models.judge_result import JudgeResult
from radicalbit_ai_gateway.utils.exceptions import JudgeParsingError
from radicalbit_ai_gateway.utils.judge.response_handler import extract_judge_result

RAW = AIMessage(
    content='{"triggered": tru', response_metadata={'finish_reason': 'stop'}
)
RESULT = JudgeResult(triggered=False)


def test_a_parsing_error_given_as_text_is_raised_as_a_parsing_error():
    with pytest.raises(JudgeParsingError) as raised:
        extract_judge_result(
            {'raw': RAW, 'parsed': RESULT, 'parsing_error': 'Expecting value'},
            model_id='judge',
        )

    error = raised.value
    assert isinstance(error.original_error, ValueError)
    assert str(error.original_error) == 'Expecting value'
    assert error.raw_content == '{"triggered": tru'
    assert error.code == 'judge_parsing_internal_error'


def test_an_empty_parsing_error_is_no_error():
    result = extract_judge_result(
        {'raw': RAW, 'parsed': RESULT, 'parsing_error': ''}, model_id='judge'
    )

    assert result is RESULT
