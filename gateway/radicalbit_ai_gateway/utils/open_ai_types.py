"""Wrapper for OpenAI types to make them compatible with Pydantic.

Pydantic doesn't support Iterable[T] well, so we use list[T] instead for tool_calls,
https://github.com/pydantic/pydantic/issues/9541

Otherwise we are using OpenAI SDK types directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal, TypeAlias, Union

from fastapi import UploadFile
from openai._types import SequenceNotStr
from openai.types.chat.chat_completion_assistant_message_param import (
    ChatCompletionAssistantMessageParam,
)
from openai.types.chat.chat_completion_audio_param import ChatCompletionAudioParam
from openai.types.chat.chat_completion_content_part_param import (
    ChatCompletionContentPartParam,
)
from openai.types.chat.chat_completion_developer_message_param import (
    ChatCompletionDeveloperMessageParam,
)
from openai.types.chat.chat_completion_function_call_option_param import (
    ChatCompletionFunctionCallOptionParam,
)
from openai.types.chat.chat_completion_function_message_param import (
    ChatCompletionFunctionMessageParam,
)
from openai.types.chat.chat_completion_prediction_content_param import (
    ChatCompletionPredictionContentParam,
)
from openai.types.chat.chat_completion_stream_options_param import (
    ChatCompletionStreamOptionsParam,
)
from openai.types.chat.chat_completion_system_message_param import (
    ChatCompletionSystemMessageParam,
)
from openai.types.chat.chat_completion_tool_choice_option_param import (
    ChatCompletionToolChoiceOptionParam,
)
from openai.types.chat.chat_completion_tool_message_param import (
    ChatCompletionToolMessageParam,
)
from openai.types.chat.chat_completion_tool_union_param import (
    ChatCompletionToolUnionParam,
)
from openai.types.shared.chat_model import ChatModel
from openai.types.shared.reasoning_effort import ReasoningEffort
from openai.types.shared_params.function_parameters import FunctionParameters
from openai.types.shared_params.metadata import Metadata
from openai.types.shared_params.response_format_json_object import (
    ResponseFormatJSONObject,
)
from openai.types.shared_params.response_format_json_schema import (
    ResponseFormatJSONSchema,
)
from openai.types.shared_params.response_format_text import ResponseFormatText
from pydantic import BaseModel
from typing_extensions import Required, TypedDict


class ChatCompletionUserMessageParamCustom(TypedDict, total=False):
    content: Required[Union[str, list[ChatCompletionContentPartParam]]]
    """The contents of the user message."""

    role: Required[Literal['user']]
    """The role of the messages author, in this case `user`."""

    name: str
    """An optional name for the participant.

    Provides the model information to differentiate between participants of the same
    role.
    """


ChatCompletionMessageParamCustom: TypeAlias = Union[
    ChatCompletionDeveloperMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParamCustom,
    ChatCompletionAssistantMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionFunctionMessageParam,
]


class CompletionCreateParamsBaseCustom(TypedDict, total=False):
    messages: Required[list[ChatCompletionMessageParamCustom]]
    """A list of messages comprising the conversation so far.

    Depending on the [model](https://platform.openai.com/docs/models) you use,
    different message types (modalities) are supported, like
    [text](https://platform.openai.com/docs/guides/text-generation),
    [images](https://platform.openai.com/docs/guides/vision), and
    [audio](https://platform.openai.com/docs/guides/audio).
    """

    model: Required[Union[str, ChatModel]]
    """Model ID used to generate the response, like `gpt-4o` or `o3`.

    OpenAI offers a wide range of models with different capabilities, performance
    characteristics, and price points. Refer to the
    [model guide](https://platform.openai.com/docs/models) to browse and compare
    available models.
    """

    audio: ChatCompletionAudioParam | None
    """Parameters for audio output.

    Required when audio output is requested with `modalities: ["audio"]`.
    [Learn more](https://platform.openai.com/docs/guides/audio).
    """

    frequency_penalty: float | None
    """Number between -2.0 and 2.0.

    Positive values penalize new tokens based on their existing frequency in the
    text so far, decreasing the model's likelihood to repeat the same line verbatim.
    """

    function_call: FunctionCall
    """Deprecated in favor of `tool_choice`.

    Controls which (if any) function is called by the model.

    `none` means the model will not call a function and instead generates a message.

    `auto` means the model can pick between generating a message or calling a
    function.

    Specifying a particular function via `{"name": "my_function"}` forces the model
    to call that function.

    `none` is the default when no functions are present. `auto` is the default if
    functions are present.
    """

    functions: Iterable[Function]
    """Deprecated in favor of `tools`.

    A list of functions the model may generate JSON inputs for.
    """

    logit_bias: dict[str, int] | None
    """Modify the likelihood of specified tokens appearing in the completion.

    Accepts a JSON object that maps tokens (specified by their token ID in the
    tokenizer) to an associated bias value from -100 to 100. Mathematically, the
    bias is added to the logits generated by the model prior to sampling. The exact
    effect will vary per model, but values between -1 and 1 should decrease or
    increase likelihood of selection; values like -100 or 100 should result in a ban
    or exclusive selection of the relevant token.
    """

    logprobs: bool | None
    """Whether to return log probabilities of the output tokens or not.

    If true, returns the log probabilities of each output token returned in the
    `content` of `message`.
    """

    max_completion_tokens: int | None
    """
    An upper bound for the number of tokens that can be generated for a completion,
    including visible output tokens and
    [reasoning tokens](https://platform.openai.com/docs/guides/reasoning).
    """

    max_tokens: int | None
    """
    The maximum number of [tokens](/tokenizer) that can be generated in the chat
    completion. This value can be used to control
    [costs](https://openai.com/api/pricing/) for text generated via API.

    This value is now deprecated in favor of `max_completion_tokens`, and is not
    compatible with
    [o-series models](https://platform.openai.com/docs/guides/reasoning).
    """

    metadata: Metadata | None
    """Set of 16 key-value pairs that can be attached to an object.

    This can be useful for storing additional information about the object in a
    structured format, and querying for objects via API or the dashboard.

    Keys are strings with a maximum length of 64 characters. Values are strings with
    a maximum length of 512 characters.
    """

    modalities: list[Literal['text', 'audio']] | None
    """
    Output types that you would like the model to generate. Most models are capable
    of generating text, which is the default:

    `["text"]`

    The `gpt-4o-audio-preview` model can also be used to
    [generate audio](https://platform.openai.com/docs/guides/audio). To request that
    this model generate both text and audio responses, you can use:

    `["text", "audio"]`
    """

    n: int | None
    """How many chat completion choices to generate for each input message.

    Note that you will be charged based on the number of generated tokens across all
    of the choices. Keep `n` as `1` to minimize costs.
    """

    parallel_tool_calls: bool
    """
    Whether to enable
    [parallel function calling](https://platform.openai.com/docs/guides/function-calling#configuring-parallel-function-calling)
    during tool use.
    """

    prediction: ChatCompletionPredictionContentParam | None
    """
    Static predicted output content, such as the content of a text file that is
    being regenerated.
    """

    presence_penalty: float | None
    """Number between -2.0 and 2.0.

    Positive values penalize new tokens based on whether they appear in the text so
    far, increasing the model's likelihood to talk about new topics.
    """

    prompt_cache_key: str
    """
    Used by OpenAI to cache responses for similar requests to optimize your cache
    hit rates. Replaces the `user` field.
    [Learn more](https://platform.openai.com/docs/guides/prompt-caching).
    """

    reasoning_effort: ReasoningEffort | None
    """
    Constrains effort on reasoning for
    [reasoning models](https://platform.openai.com/docs/guides/reasoning). Currently
    supported values are `minimal`, `low`, `medium`, and `high`. Reducing reasoning
    effort can result in faster responses and fewer tokens used on reasoning in a
    response.
    """

    response_format: ResponseFormat
    """An object specifying the format that the model must output.

    Setting to `{ "type": "json_schema", "json_schema": {...} }` enables Structured
    Outputs which ensures the model will match your supplied JSON schema. Learn more
    in the
    [Structured Outputs guide](https://platform.openai.com/docs/guides/structured-outputs).

    Setting to `{ "type": "json_object" }` enables the older JSON mode, which
    ensures the message the model generates is valid JSON. Using `json_schema` is
    preferred for models that support it.
    """

    safety_identifier: str
    """
    A stable identifier used to help detect users of your application that may be
    violating OpenAI's usage policies. The IDs should be a string that uniquely
    identifies each user. We recommend hashing their username or email address, in
    order to avoid sending us any identifying information.
    [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).
    """

    seed: int | None
    """
    This feature is in Beta. If specified, our system will make a best effort to
    sample deterministically, such that repeated requests with the same `seed` and
    parameters should return the same result. Determinism is not guaranteed, and you
    should refer to the `system_fingerprint` response parameter to monitor changes
    in the backend.
    """

    service_tier: Literal['auto', 'default', 'flex', 'scale', 'priority'] | None
    """Specifies the processing type used for serving the request.

    - If set to 'auto', then the request will be processed with the service tier
      configured in the Project settings. Unless otherwise configured, the Project
      will use 'default'.
    - If set to 'default', then the request will be processed with the standard
      pricing and performance for the selected model.
    - If set to '[flex](https://platform.openai.com/docs/guides/flex-processing)' or
      '[priority](https://openai.com/api-priority-processing/)', then the request
      will be processed with the corresponding service tier.
    - When not set, the default behavior is 'auto'.

    When the `service_tier` parameter is set, the response body will include the
    `service_tier` value based on the processing mode actually used to serve the
    request. This response value may be different from the value set in the
    parameter.
    """

    stop: Union[str | None, SequenceNotStr[str], None]
    """Not supported with latest reasoning models `o3` and `o4-mini`.

    Up to 4 sequences where the API will stop generating further tokens. The
    returned text will not contain the stop sequence.
    """

    store: bool | None
    """
    Whether or not to store the output of this chat completion request for use in
    our [model distillation](https://platform.openai.com/docs/guides/distillation)
    or [evals](https://platform.openai.com/docs/guides/evals) products.

    Supports text and image inputs. Note: image inputs over 8MB will be dropped.
    """

    stream_options: ChatCompletionStreamOptionsParam | None
    """Options for streaming response. Only set this when you set `stream: true`."""

    temperature: float | None
    """What sampling temperature to use, between 0 and 2.

    Higher values like 0.8 will make the output more random, while lower values like
    0.2 will make it more focused and deterministic. We generally recommend altering
    this or `top_p` but not both.
    """

    tool_choice: ChatCompletionToolChoiceOptionParam
    """
    Controls which (if any) tool is called by the model. `none` means the model will
    not call any tool and instead generates a message. `auto` means the model can
    pick between generating a message or calling one or more tools. `required` means
    the model must call one or more tools. Specifying a particular tool via
    `{"type": "function", "function": {"name": "my_function"}}` forces the model to
    call that tool.

    `none` is the default when no tools are present. `auto` is the default if tools
    are present.
    """

    tools: Iterable[ChatCompletionToolUnionParam]
    """A list of tools the model may call.

    You can provide either
    [custom tools](https://platform.openai.com/docs/guides/function-calling#custom-tools)
    or [function tools](https://platform.openai.com/docs/guides/function-calling).
    """

    top_logprobs: int | None
    """
    An integer between 0 and 20 specifying the number of most likely tokens to
    return at each token position, each with an associated log probability.
    `logprobs` must be set to `true` if this parameter is used.
    """

    top_p: float | None
    """
    An alternative to sampling with temperature, called nucleus sampling, where the
    model considers the results of the tokens with top_p probability mass. So 0.1
    means only the tokens comprising the top 10% probability mass are considered.

    We generally recommend altering this or `temperature` but not both.
    """

    user: str
    """This field is being replaced by `safety_identifier` and `prompt_cache_key`.

    Use `prompt_cache_key` instead to maintain caching optimizations. A stable
    identifier for your end-users. Used to boost cache hit rates by better bucketing
    similar requests and to help OpenAI detect and prevent abuse.
    [Learn more](https://platform.openai.com/docs/guides/safety-best-practices#safety-identifiers).
    """

    verbosity: Literal['low', 'medium', 'high'] | None
    """Constrains the verbosity of the model's response.

    Lower values will result in more concise responses, while higher values will
    result in more verbose responses. Currently supported values are `low`,
    `medium`, and `high`.
    """

    web_search_options: WebSearchOptions
    """
    This tool searches the web for relevant results to use in a response. Learn more
    about the
    [web search tool](https://platform.openai.com/docs/guides/tools-web-search?api-mode=chat).
    """


FunctionCall: TypeAlias = Union[
    Literal['none', 'auto'], ChatCompletionFunctionCallOptionParam
]


class Function(TypedDict, total=False):
    name: Required[str]
    """The name of the function to be called.

    Must be a-z, A-Z, 0-9, or contain underscores and dashes, with a maximum length
    of 64.
    """

    description: str
    """
    A description of what the function does, used by the model to choose when and
    how to call the function.
    """

    parameters: FunctionParameters
    """The parameters the functions accepts, described as a JSON Schema object.

    See the [guide](https://platform.openai.com/docs/guides/function-calling) for
    examples, and the
    [JSON Schema reference](https://json-schema.org/understanding-json-schema/) for
    documentation about the format.

    Omitting `parameters` defines a function with an empty parameter list.
    """


ResponseFormat: TypeAlias = Union[
    ResponseFormatText, ResponseFormatJSONSchema, ResponseFormatJSONObject
]


class WebSearchOptionsUserLocationApproximate(TypedDict, total=False):
    city: str
    """Free text input for the city of the user, e.g. `San Francisco`."""

    country: str
    """
    The two-letter [ISO country code](https://en.wikipedia.org/wiki/ISO_3166-1) of
    the user, e.g. `US`.
    """

    region: str
    """Free text input for the region of the user, e.g. `California`."""

    timezone: str
    """
    The [IANA timezone](https://timeapi.io/documentation/iana-timezones) of the
    user, e.g. `America/Los_Angeles`.
    """


class WebSearchOptionsUserLocation(TypedDict, total=False):
    approximate: Required[WebSearchOptionsUserLocationApproximate]
    """Approximate location parameters for the search."""

    type: Required[Literal['approximate']]
    """The type of location approximation. Always `approximate`."""


class WebSearchOptions(TypedDict, total=False):
    search_context_size: Literal['low', 'medium', 'high']
    """
    High level guidance for the amount of context window space to use for the
    search. One of `low`, `medium`, or `high`. `medium` is the default.
    """

    user_location: WebSearchOptionsUserLocation | None
    """Approximate location parameters for the search."""


class CompletionCreateParamsNonStreaming(CompletionCreateParamsBaseCustom, total=False):
    stream: Literal[False] | None
    """
    If set to true, the model response data will be streamed to the client as it is
    generated using
    [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
    See the
    [Streaming section below](https://platform.openai.com/docs/api-reference/chat/streaming)
    for more information, along with the
    [streaming responses](https://platform.openai.com/docs/guides/streaming-responses)
    guide for more information on how to handle the streaming events.
    """


class CompletionCreateParamsStreaming(CompletionCreateParamsBaseCustom, total=False):
    stream: Required[Literal[True]]
    """
    If set to true, the model response data will be streamed to the client as it is
    generated using
    [server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#Event_stream_format).
    See the
    [Streaming section below](https://platform.openai.com/docs/api-reference/chat/streaming)
    for more information, along with the
    [streaming responses](https://platform.openai.com/docs/guides/streaming-responses)
    guide for more information on how to handle the streaming events.
    """


CompletionCreateParams = Union[
    CompletionCreateParamsNonStreaming, CompletionCreateParamsStreaming
]


# ---------------------------------------------------------------------------
# Responses API (POST /v1/responses)
# ---------------------------------------------------------------------------
# A minimal TypedDict for the Responses API create params.  We use `list`
# instead of `Iterable` and `Any` for union-heavy fields so that FastAPI /
# Pydantic can parse the request body without issues.
# ---------------------------------------------------------------------------


class ResponseCreateParamsCustom(TypedDict, total=False):
    input: Required[Union[str, list]]
    """The input to the model — a string or list of EasyInputMessage items."""

    model: Required[Union[str, ChatModel]]
    """Gateway route name used to select the backend model."""

    instructions: str | None
    """System-level instructions for the model."""

    stream: bool | None
    """Whether to stream the response."""

    tools: list
    """Function tools (other built-in tool types are skipped by the gateway)."""

    tool_choice: Any
    """Which tool the model should use."""

    temperature: float | None
    """Sampling temperature."""

    top_p: float | None
    """Nucleus sampling probability."""

    max_output_tokens: int | None
    """Maximum number of output tokens."""

    metadata: Metadata | None
    """Key-value pairs attached to the response."""

    previous_response_id: str | None
    """Not supported — will raise GatewayBadRequest if set."""

    store: bool | None
    """Whether to store the response (no-op in the gateway)."""

    user: str | None
    """End-user identifier forwarded to the upstream provider."""

    parallel_tool_calls: bool | None
    """Whether to allow parallel tool calls (forwarded to Chat Completions)."""


# ---------------------------------------------------------------------------
# Audio transcriptions API (POST /v1/audio/transcriptions)
# ---------------------------------------------------------------------------
# This one is a `pydantic.BaseModel`, not a TypedDict: FastAPI's
# `Annotated[X, Form()]` multipart grouping only accepts a `BaseModel`.
# ---------------------------------------------------------------------------


class TranscriptionCreateParamsCustom(BaseModel):
    model: str
    """Gateway route name used to select the backend model."""

    file: UploadFile
    """The audio file to transcribe."""

    language: str | None = None
    """The language of the input audio, in ISO-639-1 format (e.g. `en`)."""

    prompt: str | None = None
    """An optional text to guide the model's style or continue a previous audio segment."""

    response_format: Literal['json', 'verbose_json'] = 'json'
    """The format of the transcript output. verbose_json is only supported for whisper-1;
    text/srt/vtt aren't supported yet."""

    stream: bool = False
    """Stream the transcript as it's generated via SSE. Only supported for the
    gpt-4o-transcribe family; whisper-1 does not support streaming."""

    temperature: float | None = None
    """Sampling temperature, between 0 and 1."""
