import Lucide from '@Components/lucide';
import useModals from '@Hooks/use-modals';
import { formatInt, formatMs } from '@Src/helpers/column-formatters';
import { useGetRequestByIdVertical } from '@State/requests/vertical-hooks';
import { useGetTraceByIdVertical } from '@State/tracing/vertical-hooks';
import {
  BarChart, Board, DataTable, NewHeader, SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { SPAN_PARAM } from './constants';
import {
  isSpanError, selectedSpanId, spanTreeRows, waterfallBar,
} from './helpers';

const COLUMNS = [
  {
    key: 'name',
    render: (_, span) => <SpanName span={span} />,
    width: '45%',
  },
  {
    key: 'bar',
    render: (_, span) => <SpanBar span={span} />,
    width: '40%',
  },
  {
    align: 'right',
    key: 'duration',
    render: (_, span) => <SpanDuration span={span} />,
    width: '15%',
  },
];

const EXPANDABLE = {
  defaultExpandAllRows: true,
  expandIcon: (props) => <ExpandIcon {...props} />,
  indentSize: 16,
};

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
  const rows = spanTreeRows(tree);
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
          expandable={EXPANDABLE}
          noHead
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

function SpanName({ span }) {
  const operationCategory = span?.operationCategory;
  const spanKind = span?.spanKind;
  const spanName = span?.spanName;
  const totalTokens = span?.totalTokens;

  const category = operationCategory ?? spanKind ?? 'span';
  const subtitle = `${category} · ${formatInt(totalTokens)} tokens`;

  if (isSpanError(span)) {
    return (
      <div className="flow-root">
        <SectionTitle size="small" subtitle={subtitle} title={spanName} titleColor="error" />
      </div>
    );
  }

  return (
    <div className="flow-root">
      <SectionTitle size="small" subtitle={subtitle} title={spanName} />
    </div>
  );
}

function ExpandIcon({ expandable, expanded, onExpand, record }) {
  const handleOnClick = (e) => {
    e.stopPropagation();
    onExpand(record, e);
  };

  if (!expandable) {
    return <span className="float-left mr-2 w-4 h-4" />;
  }

  if (expanded) {
    return (
      <button aria-label="Collapse" className="float-left mr-2" onClick={handleOnClick} type="button">
        <Lucide icon={ChevronDown} />
      </button>
    );
  }

  return (
    <button aria-label="Expand" className="float-left mr-2" onClick={handleOnClick} type="button">
      <Lucide icon={ChevronRight} />
    </button>
  );
}

function SpanBar({ span }) {
  const { modalPayload } = useModals();
  const requestUuid = modalPayload?.data?.requestUuid;

  const { data: request } = useGetRequestByIdVertical(requestUuid);
  const traceId = request?.traceId;

  const { data: trace } = useGetTraceByIdVertical(traceId);
  const traceDurationMs = trace?.durationMs;

  const { offset, value } = waterfallBar(span, traceDurationMs);

  if (isSpanError(span)) {
    return <BarChart offset={offset} type="error" value={value} />;
  }

  return <BarChart offset={offset} value={value} />;
}

function SpanDuration({ span }) {
  const durationMs = span?.durationMs;

  return <span className="text-xs">{formatMs(durationMs)}</span>;
}

export default Spans;
