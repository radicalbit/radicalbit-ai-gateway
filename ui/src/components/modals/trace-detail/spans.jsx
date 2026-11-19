import Lucide from '@Components/lucide';
import useModals from '@Hooks/use-modals';
import { formatInt, formatMs } from '@Src/helpers/column-formatters';
import { useGetRequestByIdVertical } from '@State/requests/vertical-hooks';
import { useGetTraceByIdVertical } from '@State/tracing/vertical-hooks';
import {
  BarChart, Board, DataTable, NewHeader, SectionTitle, Tooltip,
} from '@radicalbit/radicalbit-design-system';
import classNames from 'classnames';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { SPAN_PARAM, SPAN_STATUS, SpanStatusEnum } from './constants';
import {
  selectedSpanId, spanLabel, spanStatus, spanTreeRows, waterfallBar,
} from './helpers';

const COLUMNS = [
  {
    key: 'span',
    render: (_, span) => <SpanRow span={span} />,
  },
];

// The design system default bar gradient needs a colour token this theme does not have.
const BAR_CLASS_NAME = '[--background:var(--coo-primary-03)]';

const EXPANDABLE = {
  defaultExpandAllRows: true,
  expandIcon: (props) => <ExpandIcon {...props} />,
  indentSize: 16,
};

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
      headerProps={{ divider: true, padding: 'compact' }}
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
      secondaryProps={{ padding: 'none' }}
      width="100%"
    />
  );
}

function SpanRow({ span }) {
  return (
    <div className="flow-root">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <SpanStatusDot span={span} />

          <SpanName span={span} />

          <SpanDuration span={span} />
        </div>

        <SpanBar span={span} />
      </div>
    </div>
  );
}

function SpanStatusDot({ span }) {
  const { className, tooltip } = SPAN_STATUS[spanStatus(span)];

  const dotClassName = classNames('h-2 w-2 shrink-0 rounded-full', className);

  return (
    <Tooltip title={tooltip}>
      <span aria-label={tooltip} className={dotClassName} role="img" />
    </Tooltip>
  );
}

function SpanName({ span }) {
  const { modalPayload } = useModals();
  const requestUuid = modalPayload?.data?.requestUuid;

  const { data: request } = useGetRequestByIdVertical(requestUuid);
  const traceId = request?.traceId;

  const { data: trace } = useGetTraceByIdVertical(traceId);
  const rootSpanId = trace?.tree?.spanId;

  const spanId = span?.spanId;
  const spanName = span?.spanName;

  const isRoot = spanId === rootSpanId;
  const label = spanLabel(span);
  const className = classNames('min-w-0 truncate text-base', {
    'font-medium': !isRoot,
    'font-semibold': isRoot,
    'text-[var(--coo-error)]': spanStatus(span) === SpanStatusEnum.ERROR,
  });

  return (
    <Tooltip title={spanName}>
      <span className={className}>{label}</span>
    </Tooltip>
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

  if (spanStatus(span) === SpanStatusEnum.ERROR) {
    return <BarChart offset={offset} type="error" value={value} />;
  }

  return <BarChart className={BAR_CLASS_NAME} offset={offset} value={value} />;
}

function SpanDuration({ span }) {
  const durationMs = span?.durationMs;

  return <span className="ml-auto shrink-0 whitespace-nowrap text-sm">{formatMs(durationMs)}</span>;
}

export default Spans;
