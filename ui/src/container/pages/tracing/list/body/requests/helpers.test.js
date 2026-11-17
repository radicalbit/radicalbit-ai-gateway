import { describe, expect, it } from 'vitest';
import {
  firedIcons, formatOffset, requestSteps, selectedRequestUuid,
} from './helpers';

const ITEMS = [{ requestUuid: 'a' }, { requestUuid: 'b' }, { requestUuid: 'c' }];

describe('selectedRequestUuid', () => {
  it('selects the request in the URL when it is on the page', () => {
    expect(selectedRequestUuid(ITEMS, 'b')).toBe('b');
  });

  it('selects the first row when the URL has no request', () => {
    expect(selectedRequestUuid(ITEMS, null)).toBe('a');
  });

  it('selects the first row when the request in the URL is not on the page', () => {
    expect(selectedRequestUuid(ITEMS, 'z')).toBe('a');
  });

  it('selects nothing on an empty page', () => {
    expect(selectedRequestUuid([], 'b')).toBeUndefined();
  });
});

describe('firedIcons', () => {
  it('lists only the icons that fired, in the Routes page order', () => {
    const icons = {
      cache: { tone: 'success', details: [{ cacheType: 'semantic' }] },
      guardrail: null,
      fallback: { tone: 'warning', details: [{ target: 'claude-sonnet', fallbackModel: 'gpt-4o' }] },
      routing: { tone: 'success', details: [{ routingName: 'smart-router', selectedModel: 'gpt-4o-mini' }] },
    };

    expect(firedIcons(icons).map(({ kind }) => kind)).toEqual(['routing', 'fallback', 'cache']);
  });

  it('carries the tone the gateway returns', () => {
    const icons = { limits: { tone: 'error', details: [{ limitScope: 'credential', category: 'request_rate' }] } };

    expect(firedIcons(icons)[0].tone).toBe('error');
  });

  it('says what happened, one line per event', () => {
    const icons = {
      routing: { tone: 'success', details: [{ routingName: 'smart-router', selectedModel: 'gpt-4o-mini' }] },
      guardrail: {
        tone: 'error',
        details: [
          { name: 'prompt-injection', behavior: 'BLOCK', position: 'input' },
          { name: 'toxicity', behavior: 'WARN', position: 'output' },
        ],
      },
      fallback: { tone: 'warning', details: [{ target: 'claude-sonnet', fallbackModel: 'gpt-4o' }] },
      limits: {
        tone: 'error',
        details: [
          { limitScope: 'credential', category: 'request_rate', thresholdPercentage: null },
          { limitScope: 'project', category: 'budget', thresholdPercentage: 80 },
        ],
      },
      cache: { tone: 'success', details: [{ cacheType: 'semantic' }] },
    };

    expect(firedIcons(icons).map(({ lines }) => lines)).toEqual([
      ['smart-router chose gpt-4o-mini'],
      ['prompt-injection blocked the input', 'toxicity warned on the output'],
      ['claude-sonnet fell back to gpt-4o'],
      ['credential request_rate limit exceeded', 'project budget at 80%'],
      ['semantic cache hit'],
    ]);
  });

  it('lists nothing when no icon fired', () => {
    expect(firedIcons({})).toEqual([]);
  });
});

const EVENT = {
  value: 1,
  cost: 0,
  modelId: null,
  modelType: null,
  isCachedTokens: false,
  cacheType: null,
  target: null,
  fallback: null,
  guardrailName: null,
  guardrailType: null,
  guardrailWhere: null,
  guardrailBehavior: null,
  isJudge: false,
  isRouting: false,
  routingName: null,
  routingSelectedModelId: null,
  mcpMethod: null,
  mcpAlias: null,
  mcpTarget: null,
  attributes: {},
  blocking: false,
};

const REQUEST = {
  requestStatus: 'success', httpStatusCode: 200, errorType: null, errorCode: null, durationMs: 182.3, events: [],
};

describe('requestSteps', () => {
  it('lists the events in time order, timed from the first one, then the response', () => {
    const steps = requestSteps({
      ...REQUEST,
      events: [
        { ...EVENT, eventType: 'OUTPUT_TOKEN_PROCESSED', timestamp: '2026-11-02T14:31:55.164Z' },
        { ...EVENT, eventType: 'MODEL_INVOCATION', timestamp: '2026-11-02T14:31:55.000Z' },
      ],
    });

    expect(steps.map(({ offsetMs, type }) => [offsetMs, type])).toEqual([
      [0, 'MODEL_INVOCATION'],
      [164, 'OUTPUT_TOKEN_PROCESSED'],
      [182.3, 'response'],
    ]);
  });

  it('shows the fields of each event type, skipping the empty and false ones', () => {
    const [step] = requestSteps({
      ...REQUEST,
      events: [{
        ...EVENT, eventType: 'INPUT_TOKEN_PROCESSED', timestamp: '2026-11-02T14:31:55.000Z', value: 298, cost: 0.0000447, modelId: 'gpt-4o-mini', isJudge: true,
      }],
    });

    expect(step.fields).toEqual([
      { name: 'value', value: '298' },
      { name: 'cost', value: '< $0.001' },
      { name: 'modelId', value: 'gpt-4o-mini' },
      { name: 'isJudge', value: 'true' },
    ]);
  });

  it('reads the limit fields from the attributes', () => {
    const [step] = requestSteps({
      ...REQUEST,
      events: [{
        ...EVENT,
        eventType: 'LIMIT_THRESHOLD',
        timestamp: '2026-11-02T14:31:55.000Z',
        attributes: {
          limit_scope: 'project', category: 'budget', window_seconds: '2592000', maximum: '50', consumption: '40.12', threshold_percentage: '80',
        },
      }],
    });

    expect(step.fields).toEqual([
      { name: 'threshold_percentage', value: '80' },
      { name: 'limit_scope', value: 'project' },
      { name: 'category', value: 'budget' },
      { name: 'consumption', value: '40.12' },
      { name: 'maximum', value: '50' },
      { name: 'window_seconds', value: '2592000' },
    ]);
  });

  it('shows every field of an event type it does not know', () => {
    const [step] = requestSteps({
      ...REQUEST,
      events: [{ ...EVENT, eventType: 'NEW_EVENT', timestamp: '2026-11-02T14:31:55.000Z', modelId: 'jev' }],
    });

    expect(step.fields).toEqual([
      { name: 'value', value: '1' },
      { name: 'cost', value: '$0.000' },
      { name: 'modelId', value: 'jev' },
    ]);
  });

  it('adds the attributes of an event type it does not know', () => {
    const [step] = requestSteps({
      ...REQUEST,
      events: [{
        ...EVENT, eventType: 'NEW_EVENT', timestamp: '2026-11-02T14:31:55.000Z', attributes: { shard: 'eu-1' },
      }],
    });

    expect(step.fields).toContainEqual({ name: 'shard', value: 'eu-1' });
  });

  it('never shows the guardrail parameters', () => {
    const steps = requestSteps({
      ...REQUEST,
      events: [{ ...EVENT, eventType: 'GUARDRAIL_PARAMS', timestamp: '2026-11-02T14:31:55.000Z' }],
    });

    expect(steps.map(({ type }) => type)).toEqual(['response']);
  });

  it('marks the blocking event and gives each step its tone', () => {
    const steps = requestSteps({
      ...REQUEST,
      requestStatus: 'handled_error',
      events: [
        { ...EVENT, eventType: 'MODEL_INVOCATION', timestamp: '2026-11-02T14:31:55.000Z' },
        { ...EVENT, eventType: 'INPUT_TOKEN_PROCESSED', timestamp: '2026-11-02T14:31:55.001Z' },
        { ...EVENT, eventType: 'ROUTING', timestamp: '2026-11-02T14:31:55.002Z' },
        { ...EVENT, eventType: 'FALLBACK', timestamp: '2026-11-02T14:31:55.003Z' },
        { ...EVENT, eventType: 'GUARDRAIL', timestamp: '2026-11-02T14:31:55.004Z', guardrailBehavior: 'WARN' },
        { ...EVENT, eventType: 'GUARDRAIL', timestamp: '2026-11-02T14:31:55.005Z', guardrailBehavior: 'BLOCK', blocking: true },
      ],
    });

    expect(steps.map(({ blocking, tone }) => [tone, blocking])).toEqual([
      ['neutral', false],
      ['muted', false],
      ['primary', false],
      ['warning', false],
      ['warning', false],
      ['error', true],
      ['error', false],
    ]);
  });

  it('ends with the response: its status, HTTP code and error', () => {
    const steps = requestSteps({
      ...REQUEST, requestStatus: 'handled_error', httpStatusCode: 429, errorType: 'RateLimitError', errorCode: 'rate_limit_exceeded',
    });

    expect(steps).toEqual([{
      key: 'response',
      offsetMs: 182.3,
      type: 'response',
      blocking: false,
      tone: 'error',
      fields: [
        { name: 'requestStatus', value: 'handled_error' },
        { name: 'httpStatusCode', value: '429' },
        { name: 'errorType', value: 'RateLimitError' },
        { name: 'errorCode', value: 'rate_limit_exceeded' },
      ],
    }]);
  });

  it('gives a response with an unknown status the neutral tone', () => {
    const [response] = requestSteps({ ...REQUEST, requestStatus: null });

    expect(response.tone).toBe('neutral');
  });

  it('gives a successful response the success tone', () => {
    const [response] = requestSteps(REQUEST);

    expect(response.tone).toBe('success');
  });
});

describe('formatOffset', () => {
  it('shows the start as 0 ms', () => {
    expect(formatOffset(0)).toBe('0 ms');
  });

  it('keeps two decimals below 10 ms', () => {
    expect(formatOffset(0.514)).toBe('0.51 ms');
  });

  it('rounds to whole milliseconds below one second', () => {
    expect(formatOffset(182.3)).toBe('182 ms');
  });

  it('switches to seconds from one second', () => {
    expect(formatOffset(3921.4)).toBe('3.92 s');
  });
});
