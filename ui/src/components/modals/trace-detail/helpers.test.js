import { describe, expect, it } from 'vitest';
import {
  attributeCount,
  attributeGroups,
  flattenSpans,
  isSpanError,
  selectedSpanId,
  selectedSpanTab,
  spanIo,
  spanErrorLines,
  spanShare,
  spanTreeRows,
  waterfallBar,
} from './helpers';

const TREE = {
  spanId: 'root',
  spanName: 'chat.workflow',
  durationMs: 100,
  startOffsetMs: 0,
  operationCategory: 'endpoint',
  children: [
    {
      spanId: 'auth',
      spanName: 'auth_api_key.task',
      durationMs: 10,
      startOffsetMs: 0,
      operationCategory: 'auth',
      children: [],
    },
    {
      spanId: 'guard',
      spanName: 'guardrail.task',
      durationMs: 40,
      startOffsetMs: 10,
      operationCategory: 'guardrail_input',
      children: [
        {
          spanId: 'judge',
          spanName: 'judge.task',
          durationMs: 30,
          startOffsetMs: 15,
          operationCategory: 'invocation',
          children: [],
        },
      ],
    },
    {
      spanId: 'invoke',
      spanName: 'invoke.task',
      durationMs: 60,
      startOffsetMs: 20,
      operationCategory: 'invocation',
      children: [],
    },
  ],
};

describe('flattenSpans', () => {
  it('lists the spans in tree order with their depth', () => {
    expect(flattenSpans(TREE).map(({ depth, span }) => [span.spanId, depth])).toEqual([
      ['root', 0],
      ['auth', 1],
      ['guard', 1],
      ['judge', 2],
      ['invoke', 1],
    ]);
  });

  it('lists nothing without a tree', () => {
    expect(flattenSpans(null)).toEqual([]);
  });
});

describe('selectedSpanId', () => {
  it('selects the span in the URL when it is in the tree', () => {
    expect(selectedSpanId(TREE, 'auth')).toBe('auth');
  });

  it('selects the first invocation span when the URL has no span', () => {
    expect(selectedSpanId(TREE, null)).toBe('judge');
  });

  it('selects the first invocation span when the span in the URL is not in the tree', () => {
    expect(selectedSpanId(TREE, 'gone')).toBe('judge');
  });

  it('selects the root when no span is an invocation', () => {
    const tree = { spanId: 'root', operationCategory: 'endpoint', children: [{ spanId: 'auth', operationCategory: 'auth', children: [] }] };

    expect(selectedSpanId(tree, null)).toBe('root');
  });

  it('selects nothing without a tree', () => {
    expect(selectedSpanId(null, 'auth')).toBeUndefined();
  });
});

describe('selectedSpanTab', () => {
  it('keeps a known tab from the URL', () => {
    expect(selectedSpanTab('attributes')).toBe('attributes');
  });

  it('falls back to Input for a missing or unknown tab', () => {
    expect(selectedSpanTab(null)).toBe('input');
    expect(selectedSpanTab('events')).toBe('input');
  });
});

describe('isSpanError', () => {
  it('flags a span with an Error status code', () => {
    expect(isSpanError({ statusCode: 'Error', errorCount: 0 })).toBe(true);
  });

  it('flags a span with errors', () => {
    expect(isSpanError({ statusCode: 'Unset', errorCount: 2 })).toBe(true);
  });

  it('does not flag a clean span', () => {
    expect(isSpanError({ statusCode: 'Unset', errorCount: 0 })).toBe(false);
  });
});

describe('waterfallBar', () => {
  it('places the bar by start offset and sizes it by duration, in percent of the trace', () => {
    expect(waterfallBar({ startOffsetMs: 20, durationMs: 60 }, 100)).toEqual({ offset: 20, value: 60 });
  });

  it('lets parallel spans overlap', () => {
    const judge = waterfallBar({ startOffsetMs: 15, durationMs: 30 }, 100);
    const invoke = waterfallBar({ startOffsetMs: 20, durationMs: 60 }, 100);

    expect(invoke.offset).toBeLessThan(judge.offset + judge.value);
  });

  it('keeps the bar inside the track', () => {
    expect(waterfallBar({ startOffsetMs: 90, durationMs: 30 }, 100)).toEqual({ offset: 90, value: 10 });
  });

  it('draws nothing for a trace with no duration', () => {
    expect(waterfallBar({ startOffsetMs: 0, durationMs: 0 }, 0)).toEqual({ offset: 0, value: 0 });
  });
});

describe('spanShare', () => {
  it('gives the rounded percent of the trace the span takes', () => {
    expect(spanShare({ durationMs: 4.681042 }, 13.026375)).toBe(36);
  });

  it('gives 0 for a trace with no duration', () => {
    expect(spanShare({ durationMs: 3 }, 0)).toBe(0);
  });
});

describe('spanIo', () => {
  it('parses a JSON string into JSON', () => {
    expect(spanIo({ 'traceloop.entity.input': '{"args":["a"],"kwargs":{}}' }, 'input')).toEqual({ type: 'json', value: { args: ['a'], kwargs: {} } });
  });

  it('keeps an object as JSON', () => {
    expect(spanIo({ 'traceloop.entity.output': { answer: 'refund' } }, 'output')).toEqual({ type: 'json', value: { answer: 'refund' } });
  });

  it('parses a JSON object that was encoded twice', () => {
    const output = JSON.stringify(JSON.stringify({ id: 'a', choices: [] }));

    expect(spanIo({ 'traceloop.entity.output': output }, 'output')).toEqual({ type: 'json', value: { id: 'a', choices: [] } });
  });

  it('shows plain text when the value is not JSON', () => {
    expect(spanIo({ 'traceloop.entity.output': 'hello' }, 'output')).toEqual({ type: 'text', value: 'hello' });
  });

  it('shows a JSON scalar as text', () => {
    expect(spanIo({ 'traceloop.entity.output': '42' }, 'output')).toEqual({ type: 'text', value: '42' });
  });

  it('is empty when the span did not record it', () => {
    expect(spanIo({}, 'input')).toEqual({ type: 'empty' });
    expect(spanIo({ 'traceloop.entity.input': '' }, 'input')).toEqual({ type: 'empty' });
    expect(spanIo(undefined, 'input')).toEqual({ type: 'empty' });
  });
});

const ATTRIBUTES = {
  'traceloop.entity.input': '{}',
  'traceloop.entity.output': '{}',
  'decision.request.state': 'My card was charged twice',
  'decision.request.questions': '{"intent":{"type":"choice"}}',
  'gen_ai.usage.input_tokens': 1,
  'traceloop.association.properties.route_name': 'decide-plain',
  'traceloop.span.kind': 'task',
};

describe('attributeGroups', () => {
  it('groups the attributes by prefix, strips the prefix, leaves out input and output', () => {
    expect(attributeGroups(ATTRIBUTES)).toEqual([
      {
        title: 'Decision',
        items: [
          { name: 'request.state', value: 'My card was charged twice' },
          { name: 'request.questions', value: { intent: { type: 'choice' } } },
        ],
      },
      { title: 'Usage', items: [{ name: 'input_tokens', value: 1 }] },
      { title: 'Association properties', items: [{ name: 'route_name', value: 'decide-plain' }] },
      { title: 'Other attributes', items: [{ name: 'traceloop.span.kind', value: 'task' }] },
    ]);
  });

  it('leaves out empty groups', () => {
    expect(attributeGroups({ 'traceloop.span.kind': 'task' })).toEqual([
      { title: 'Other attributes', items: [{ name: 'traceloop.span.kind', value: 'task' }] },
    ]);
  });

  it('has no groups without attributes', () => {
    expect(attributeGroups(undefined)).toEqual([]);
  });
});

describe('attributeCount', () => {
  it('counts the attributes shown in the Attributes tab', () => {
    expect(attributeCount(ATTRIBUTES)).toBe(5);
  });
});

describe('spanErrorLines', () => {
  it('lists the status message, then each error event message, once', () => {
    const span = {
      statusMessage: '[CREDENTIAL RATE LIMIT] limit=3',
      errorEvents: [
        { name: 'exception', attributes: { 'exception.message': '[CREDENTIAL RATE LIMIT] limit=3' } },
        { name: 'exception', attributes: { 'exception.message': 'upstream timeout' } },
      ],
    };

    expect(spanErrorLines(span)).toEqual(['[CREDENTIAL RATE LIMIT] limit=3', 'upstream timeout']);
  });

  it('falls back to the event name when the event has no message', () => {
    expect(spanErrorLines({ statusMessage: null, errorEvents: [{ name: 'exception', attributes: {} }] })).toEqual(['exception']);
  });

  it('has no lines for a clean span', () => {
    expect(spanErrorLines({ statusMessage: '', errorEvents: [] })).toEqual([]);
  });
});

describe('spanTreeRows', () => {
  it('keeps the tree for the table, with children only on spans that have them', () => {
    const rows = spanTreeRows(TREE);

    expect(rows.map(({ spanId }) => spanId)).toEqual(['root']);
    expect(rows[0].children.map(({ spanId }) => spanId)).toEqual(['auth', 'guard', 'invoke']);
    expect(rows[0].children[1].children.map(({ spanId }) => spanId)).toEqual(['judge']);
    expect(rows[0].children[0]).not.toHaveProperty('children');
  });

  it('has no rows without a tree', () => {
    expect(spanTreeRows(null)).toEqual([]);
  });
});
