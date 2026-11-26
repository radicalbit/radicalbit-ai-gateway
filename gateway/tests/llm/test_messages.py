"""Gateway messages: the ``type`` tag a message is built with."""

from pydantic import ValidationError
import pytest

from radicalbit_ai_gateway.llm.messages import AIMessage, AIMessageChunk


def test_an_ai_message_rejects_the_chunk_tag():
    with pytest.raises(ValidationError, match="Input should be 'ai'"):
        AIMessage.model_validate({'content': 'hi', 'type': 'AIMessageChunk'})


def test_an_ai_message_accepts_its_own_tag():
    message = AIMessage.model_validate({'content': 'hi', 'type': 'ai'})

    assert message.type == 'ai'
    assert message.content == 'hi'


def test_a_chunk_accepts_its_own_tag():
    chunk = AIMessageChunk.model_validate({'content': 'hi', 'type': 'AIMessageChunk'})

    assert chunk.type == 'AIMessageChunk'


def test_a_dumped_chunk_is_not_read_back_as_an_ai_message():
    dumped = AIMessageChunk(content='hi').model_dump()

    with pytest.raises(ValidationError, match="Input should be 'ai'"):
        AIMessage.model_validate(dumped)
