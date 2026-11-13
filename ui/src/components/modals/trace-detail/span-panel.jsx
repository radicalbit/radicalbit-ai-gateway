import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import useModals from '@Hooks/use-modals';
import { formatInt, formatMs, formatTimestamp } from '@Src/helpers/column-formatters';
import { useGetRequestByIdVertical } from '@State/requests/vertical-hooks';
import { useGetSpanByIdVertical, useGetTraceByIdVertical } from '@State/tracing/vertical-hooks';
import {
  Alert,
  Board,
  DescriptionList,
  Json,
  NewHeader,
  SectionTitle,
  Skeleton,
  Spin,
  Tabs,
  Tag,
  TextWithBold,
} from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';
import { SPAN_PARAM, SPAN_TAB_PARAM } from './constants';
import {
  attributeCount, attributeGroups, flattenSpans, selectedSpanId, selectedSpanTab, spanErrorLines, spanIo, spanShare,
} from './helpers';

const LABEL_PROPS = { type: 'secondary' };

function SpanPanel() {
  const { modalPayload } = useModals();
  const requestUuid = modalPayload?.data?.requestUuid;

  const [searchParams] = useSearchParams();
  const spanIdParam = searchParams.get(SPAN_PARAM);

  const { data: request } = useGetRequestByIdVertical(requestUuid);
  const traceId = request?.traceId;

  const { data: trace } = useGetTraceByIdVertical(traceId);
  const tree = trace?.tree;

  const spanId = selectedSpanId(tree, spanIdParam);

  const { currentData, data, isError, isFetching, isSuccess } = useGetSpanByIdVertical({ traceId, spanId });

  const isFirstLoad = isFetching && !data;
  const isSwitching = isFetching && !currentData && !!data;

  if (isFirstLoad) {
    return <Skeleton active block />;
  }

  if (isError) {
    return <SomethingWentWrong size="small" />;
  }

  if (isSwitching) {
    return (
      <Spin spinning>
        <SpanDetail span={data} />
      </Spin>
    );
  }

  if (!isSuccess || !currentData) {
    return false;
  }

  return <SpanDetail span={currentData} />;
}

function SpanDetail({ span }) {
  const spanId = span?.spanId;
  const spanName = span?.spanName;

  return (
    <Board
      header={(
        <NewHeader
          padding="none"
          title={(
            <SectionTitle
              subtitle={<TextWithBold bold={spanId} size="small" text="Span" textProps={LABEL_PROPS} />}
              title={spanName}
              titleSuffix={<SpanTags spanId={spanId} />}
              wrapTitle
            />
          )}
        />
      )}
      main={(
        <div className="flex flex-col gap-4">
          <SpanKpis span={span} />

          <SpanErrors span={span} />

          <SpanTabs span={span} />
        </div>
      )}
      width="100%"
    />
  );
}

function SpanTags({ spanId }) {
  const { modalPayload } = useModals();
  const requestUuid = modalPayload?.data?.requestUuid;

  const { data: request } = useGetRequestByIdVertical(requestUuid);
  const traceId = request?.traceId;

  const { data: trace } = useGetTraceByIdVertical(traceId);
  const tree = trace?.tree;

  const node = flattenSpans(tree).find(({ span }) => span.spanId === spanId)?.span;
  const operationCategory = node?.operationCategory;
  const spanKind = node?.spanKind;

  const tags = [spanKind, operationCategory].filter(Boolean);

  return (
    <div className="flex items-center gap-2">
      {tags.map((tag) => <Tag key={tag} type="secondary">{tag}</Tag>)}
    </div>
  );
}

function SpanKpis({ span }) {
  const { modalPayload } = useModals();
  const requestUuid = modalPayload?.data?.requestUuid;

  const { data: request } = useGetRequestByIdVertical(requestUuid);
  const traceId = request?.traceId;

  const { data: trace } = useGetTraceByIdVertical(traceId);
  const traceDurationMs = trace?.durationMs;

  const createdAt = span?.createdAt;
  const durationMs = span?.durationMs;
  const errorCount = span?.errorCount;
  const inputTokens = span?.inputTokens;
  const outputTokens = span?.outputTokens;

  const errorType = errorCount > 0 ? 'error' : undefined;

  const items = [
    { title: 'Duration', value: formatMs(durationMs) },
    { title: 'Share', value: `${spanShare(span, traceDurationMs)}% of trace` },
    { title: 'Tokens', value: `${formatInt(inputTokens)} in · ${formatInt(outputTokens)} out` },
    { title: 'Errors', type: errorType, value: formatInt(errorCount) },
    { title: 'Created', value: formatTimestamp(createdAt).trim() },
  ];

  return <DescriptionList columns={5} items={items} layout="stacked" noMargin />;
}

function SpanErrors({ span }) {
  const lines = spanErrorLines(span);

  if (!lines.length) {
    return false;
  }

  return (
    <Alert
      description={(
        <div className="flex flex-col gap-1">
          {lines.map((line, index) => <span key={index}>{line}</span>)}
        </div>
      )}
      message="Errors"
      type="error"
    />
  );
}

function SpanTabs({ span }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeKey = selectedSpanTab(searchParams.get(SPAN_TAB_PARAM));

  const attributes = span?.attributes;

  const items = [
    { key: 'input', label: 'Input', children: <div className="pt-3"><SpanIo attributes={attributes} tab="input" /></div> },
    { key: 'output', label: 'Output', children: <div className="pt-3"><SpanIo attributes={attributes} tab="output" /></div> },
    { key: 'attributes', label: `Attributes · ${attributeCount(attributes)}`, children: <div className="pt-3"><SpanAttributes attributes={attributes} /></div> },
  ];

  const handleOnChange = (key) => {
    setSearchParams((prev) => {
      prev.set(SPAN_TAB_PARAM, key);
      return prev;
    });
  };

  return <Tabs activeKey={activeKey} items={items} onChange={handleOnChange} />;
}

function SpanIo({ attributes, tab }) {
  const { type, value } = spanIo(attributes, tab);

  if (type === 'empty') {
    return <span>Not recorded for this span.</span>;
  }

  if (type === 'json') {
    return <Json data={value} expandUntil={1} />;
  }

  return <span className="whitespace-pre-wrap break-all">{value}</span>;
}

function SpanAttributes({ attributes }) {
  const groups = attributeGroups(attributes);

  if (!groups.length) {
    return <span>No attributes recorded for this span.</span>;
  }

  return (
    <div className="flex flex-col gap-4">
      {groups.map(({ items, title }) => (
        <AttributeGroup key={title} items={items} title={title} />
      ))}
    </div>
  );
}

function AttributeGroup({ items, title }) {
  const listItems = items.map(({ name, value }) => ({ title: name, value: <AttributeValue value={value} /> }));

  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <TextWithBold bold={items.length} boldProps={LABEL_PROPS} text={<strong>{`${title} ·`}</strong>} />

      <DescriptionList items={listItems} noMargin />
    </section>
  );
}

function AttributeValue({ value }) {
  if (value !== null && typeof value === 'object') {
    return <Json data={value} expandUntil={1} />;
  }

  return String(value);
}

export default SpanPanel;
