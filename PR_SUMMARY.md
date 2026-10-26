## Summary

New guardrail type `decision_judge` (AG-1024, AG-1025, AG-1026). It asks a decision model (Jev, via Typesafe) one yes/no Noul question about the chat input. It triggers when the probability of yes (`noul`) reaches the guardrail's `threshold`. An optional fallback decision model answers when the primary keeps failing. Bad model references are caught when the config loads, not when traffic hits.

## Description

The decision judge is a check guardrail, so block, warn and soft block work as for every other check. It reuses the LLM judge's text extraction (so `message_roles` works) and calls Typesafe with plain HTTP through the shared `httpx` client, with our own retries (network, timeout, 429, 5xx).

It fails closed, like the LLM judge. When the primary is still failing after retries, or gives no valid `noul`, the `fallback_model_id` model answers the same question and its `noul` decides. A 4xx other than 429 does not fall back: the same request would be rejected again. When nothing answers, the request fails with 500 `judge_internal_error` and the chat model is not called.

`model_id` and `fallback_model_id` must name decision models from the top-level `decision_models`. Any decision model of the project is fine, not only those on the route. The fallback must differ from `model_id`. The error names the guardrail and the id.

**Example config:**
```yaml
decision_models:
  - model_id: jev
    model: typesafe/jev-latest
    credentials:
      api_key: !secret TYPESAFE_API_KEY
  - model_id: jev-backup
    model: typesafe/jev-backup
    credentials:
      api_key: !secret TYPESAFE_API_KEY

guardrails:
  - name: toxic_decision
    type: decision_judge
    where: input
    behavior: block
    parameters:
      model_id: jev
      fallback_model_id: jev-backup   # optional
      instructions: Is this message toxic, insulting, hateful or harassing?
      criteria:                        # optional
        "true": The message contains toxic language
        "false": The message is polite or neutral
      threshold: 0.5                   # 0 to 1, default 0.5
    response_message: No toxic content allowed
```

**`POST /v1/chat/completions` with a decision judge on the input** (no request or response shape change):

| Case | Result |
|------|--------|
| `noul >= threshold`, `block` | 400 `guardrail_violation_bad_request` with `response_message` |
| `noul >= threshold`, `soft_block` | 200 refusal, `X-RB-AIGATEWAY-GUARDRAILS-TRIGGERED: true` |
| `noul >= threshold`, `warn` | 200, request goes through |
| `noul < threshold` | 200 |
| Primary fails after retries, or no valid `noul` | fallback decides, if set |
| Primary returns a 4xx other than 429 | 500 `judge_internal_error`, no fallback |
| Nothing answers | 500 `judge_internal_error`, chat model not called |

**Load errors (AG-1026):**
```
Guardrail 'toxic_decision': decision judge model 'nope' not declared in top-level decision_models.
Guardrail 'toxic_decision': decision judge fallback model 'gpt' not declared in top-level decision_models.
Guardrail 'toxic_decision': decision judge fallback model 'jev' must differ from its model.
```

**Upgrade note:** at startup a project whose saved config fails these checks is skipped (logged, the gateway keeps running), so all its routes are down until the config is fixed. Only decision judges that already pointed at a missing or non-decision model are hit. Decision judges are new, so this should only touch test configs.

## Key Changes

- **Model** `models/guardrails.py`: new `GuardrailType.DECISION_JUDGE` and `DecisionJudgeParameter` (`model_id`, `fallback_model_id`, `instructions`, `criteria`, `threshold`). Extra fields are rejected, including the LLM judge's `prompt_ref`, `temperature`, `max_tokens`, `include_reasoning`, `include_media`. A `before` validator pins the parameter type so a stray LLM judge field is rejected instead of matching `JudgeParameter`.
- **Model** `models/gateway_config.py`: `validate_judge_models` (from `main`, AG-822) now also checks the decision judge `fallback_model_id` and that it differs from `model_id`.
- **Model** `models/gateway_config_out.py`: `DecisionJudgeParameterOut`, the camelCase view in `GET /public/api/v1/projects/{project_uuid}/routes[/{route_name}]`.
- **Guardrails** `guardrails/judges/decision_judge_engine.py` (new): builds `state`, sends one Noul question, reads `noul`, falls back on failure. Any failure left is a `JudgeInternalError`.
- **Guardrails** `guardrails/guardrail_check.py`: `_check_decision_judge`, its reason payload and log line (`model_id`, `fallback_model_id`, `noul`, `threshold`).
- **Guardrails** `guardrails/guardrail_engine.py`, `utils/gateway_route_factory.py`: each project builds its decision judge engine from all its `decision_models`.
- **Invocation** `invocation/decision_model_invoker.py`: new `call(model_id, body)`. One model, with retries, no route fallback, no metrics.
- **Errors** `ai_gateway.py`: `JudgeInternalError` now passes through on chat and decision input guardrails. A judge failure is `500 judge_internal_error` instead of `500 gateway_internal_error`, LLM judges too.
- **Errors** `utils/exceptions.py`: the client `reason` drops `noul` and `threshold`, so a caller cannot tune a prompt to slip under the score. `fallback_model_id` was already dropped.
- **Tests** `tests/models/test_gateway_config_decision_judge.py` (27 cases): parsing, threshold bounds, rejected LLM judge fields, config out, and every load check.
- **Tests** `tests/test_server_decision_judge.py` (33 cases): through `/v1/chat/completions` with Typesafe and OpenAI mocked by `pook`. Covers threshold, behaviors, events, `message_roles`, retries, fail closed, fallback (5xx, 429, no connection, bad `noul`, 4xx without fallback, both fail), and streaming.

**Not in this PR:** output/embeddings/decision traffic (AG-1027), cost and limits (AG-1028), tracing (AG-1029/1030), docs (AG-1031).
