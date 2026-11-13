import useModals from '@Hooks/use-modals';
import { formatInt, formatMs } from '@Src/helpers/column-formatters';
import { useGetRequestByIdVertical } from '@State/requests/vertical-hooks';
import { useGetTraceByIdVertical } from '@State/tracing/vertical-hooks';
import {
  BarChart, Board, DataTable, NewHeader, SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';
import { SPAN_PARAM } from './constants';
import {
  flattenSpans, isSpanError, selectedSpanId, waterfallBar,
} from './helpers';

const COLUMNS = [
  {
    key: 'span',
    render: (_, span) => <SpanRow span={span} />,
  },
];

const HEADER_PROPS = { divider: true, padding: 'compact' };

const SECONDARY_PROPS = { padding: 'none' };

function Spans() {
  const { modalPayload } = useModals();
  const requestUuid = modalPayload?.data?.requestUuid;

  const [searchParams, setSearchParams] = useSearchParams();
  const spanIdParam = searchParams.get(SPAN_PARAM);

  const { data: request } = useGetRequestByIdVertical(requestUuid);
  const traceId = request?.traceId;

  const { data: trace } = useGetTraceByIdVertical(traceId);
  const durationMs = trace?.durationMs;
  const totalSpans = trace?.totalSpans;
  const tree = trace?.tree;

  const selectedId = selectedSpanId(tree, spanIdParam);
  const rows = flattenSpans(tree).map(({ depth, span }) => ({ ...span, children: undefined, depth }));
  const spansLabel = totalSpans === 1 ? '1 span' : `${formatInt(totalSpans)} spans`;
  const countLabel = `${spansLabel} · ${formatMs(durationMs)}`;

  const handleOnRow = (span) => ({
    onClick: () => {
      setSearchParams((prev) => {
        prev.set(SPAN_PARAM, span.spanId);
        return prev;
      });
    },
  });

  const handleOnRowClassName = (span) => {
    if (span.spanId === selectedId) {
      return DataTable.ROW_PRIMARY_LIGHT;
    }

    return '';
  };

  return (
    <Board
      header={(
        <NewHeader
          details={{ one: <span className="text-xs">{countLabel}</span> }}
          padding="none"
          title={<SectionTitle title="Spans" />}
        />
      )}
      headerProps={HEADER_PROPS}
      secondary={(
        <DataTable
          clickable
          columns={COLUMNS}
          dataSource={rows}
          noHead
          noPadding
          onRow={handleOnRow}
          pagination={false}
          rowClassName={handleOnRowClassName}
          rowKey="spanId"
          size="small"
        />
      )}
      secondaryProps={SECONDARY_PROPS}
      width="100%"
    />
  );
}

function SpanRow({ span }) {
  const { modalPayload } = useModals();
  const requestUuid = modalPayload?.data?.requestUuid;

  const { data: request } = useGetRequestByIdVertical(requestUuid);
  const traceId = request?.traceId;

  const { data: trace } = useGetTraceByIdVertical(traceId);
  const traceDurationMs = trace?.durationMs;

  const durationMs = span?.durationMs;
  const operationCategory = span?.operationCategory;
  const spanKind = span?.spanKind;
  const spanName = span?.spanName;
  const totalTokens = span?.totalTokens;

  const { offset, value } = waterfallBar(span, traceDurationMs);
  const category = operationCategory ?? spanKind ?? 'span';
  const subtitle = `${category} · ${formatInt(totalTokens)} tokens`;

  if (isSpanError(span)) {
    return (
      <div className="flex flex-col gap-2 px-4 py-3">
        <NewHeader
          details={{ one: <span className="text-xs">{formatMs(durationMs)}</span> }}
          padding="none"
          title={<SectionTitle size="small" subtitle={subtitle} title={spanName} titleColor="error" />}
        />

        <BarChart offset={offset} type="error" value={value} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 px-4 py-3">
      <NewHeader
        details={{ one: <span className="text-xs">{formatMs(durationMs)}</span> }}
        padding="none"
        title={<SectionTitle size="small" subtitle={subtitle} title={spanName} />}
      />

      <BarChart offset={offset} value={value} />
    </div>
  );
}

export default Spans;
