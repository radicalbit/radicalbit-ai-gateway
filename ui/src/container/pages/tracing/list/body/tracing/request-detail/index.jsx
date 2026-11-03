import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import Lucide from '@Components/lucide';
import TraceBody from '@Components/modals/trace-detail/body';
import { formatCost } from '@Src/helpers/column-formatters';
import { useGetRequestByIdVertical, useGetTraceByIdVertical } from '@State/tracing/vertical-hooks';
import {
  Board, DataTable, SectionTitle, Skeleton, Tag, Void,
} from '@radicalbit/radicalbit-design-system';
import dayjs from 'dayjs';
import { Unplug } from 'lucide-react';
import { REQUEST_STATUS_LABELS, RequestStatusEnum } from '../request-status';
import summarize from './summarize';

const OUTCOME_KEY = 'outcome';

const eventColumns = [
  {
    title: 'Time',
    dataIndex: 'timestamp',
    width: 120,
    render: (timestamp, { key }) => key !== OUTCOME_KEY && dayjs(timestamp).format('HH:mm:ss.SSS'),
  },
  {
    title: 'Event',
    dataIndex: 'eventType',
    width: 240,
    render: (eventType, { blocking }) => <EventType blocking={blocking} eventType={eventType} />,
  },
  {
    title: 'What happened',
    dataIndex: 'summary',
    render: (summary, { key, requestStatus, httpStatusCode, errorType, errorCode }) => (
      <WhatHappened
        errorCode={errorCode}
        errorType={errorType}
        httpStatusCode={httpStatusCode}
        isOutcome={key === OUTCOME_KEY}
        requestStatus={requestStatus}
        summary={summary}
      />
    ),
  },
  {
    title: 'Cost',
    dataIndex: 'cost',
    align: 'right',
    width: 120,
    render: (cost) => (cost ? formatCost(cost) : ''),
  },
  {
    title: 'Attributes',
    dataIndex: 'attributes',
    render: (attributes) => <Attributes attributes={attributes} />,
  },
];

const toEventRow = (event, index) => ({
  ...event,
  key: `${index}-${event.eventType}`,
  summary: summarize(event),
});

// Always the last row: how the request ended, from its request_event row.
const toOutcomeRow = ({ requestStatus, httpStatusCode, errorType, errorCode }) => ({
  key: OUTCOME_KEY,
  eventType: 'Outcome',
  requestStatus,
  httpStatusCode,
  errorType,
  errorCode,
  attributes: {},
});

const rowClassName = ({ key, blocking, requestStatus }) => {
  if (blocking) {
    return DataTable.ROW_ERROR;
  }

  if (key === OUTCOME_KEY && requestStatus !== RequestStatusEnum.SUCCESS) {
    return DataTable.ROW_ERROR;
  }

  if (key === OUTCOME_KEY) {
    return DataTable.ROW_LIGHT;
  }

  return undefined;
};

/**
 * The detail of one request, expanded in place under its row: its events in
 * time order ending with the Outcome row, then its trace (AG-1109).
 */
function RequestDetail({ requestUuid }) {
  const { data, isLoading, isError, isSuccess } = useGetRequestByIdVertical(requestUuid);
  const events = data?.events ?? [];
  const traceId = data?.traceId;

  if (isLoading) {
    return <Skeleton active block />;
  }

  if (isError) {
    return <SomethingWentWrong size="small" />;
  }

  if (!isSuccess) {
    return false;
  }

  const rows = [...events.map(toEventRow), toOutcomeRow(data)];

  return (
    <div className="flex flex-col gap-4 py-2">
      <DataTable
        columns={eventColumns}
        dataSource={rows}
        pagination={false}
        rowClassName={rowClassName}
        rowKey="key"
        size="small"
      />

      <Trace traceId={traceId} />
    </div>
  );
}

function EventType({ blocking, eventType }) {
  if (blocking) {
    return (
      <div className="flex items-center gap-2">
        <code>{eventType}</code>

        <Tag type="error">Blocking</Tag>
      </div>
    );
  }

  return <code>{eventType}</code>;
}

// The Outcome row reads its fields from the row data; every other row has a summary.
function WhatHappened({
  errorCode, errorType, httpStatusCode, isOutcome, requestStatus, summary,
}) {
  if (isOutcome) {
    return <Outcome errorCode={errorCode} errorType={errorType} httpStatusCode={httpStatusCode} requestStatus={requestStatus} />;
  }

  return summary;
}

function Outcome({ requestStatus, httpStatusCode, errorType, errorCode }) {
  const status = REQUEST_STATUS_LABELS[requestStatus] ?? requestStatus ?? '--';

  return (
    <div className="flex flex-wrap gap-x-6 gap-y-1">
      <OutcomeField label="Status" value={status} />

      <OutcomeField label="HTTP code" value={httpStatusCode} />

      <OutcomeField label="Error type" value={errorType} />

      <OutcomeField label="Error code" value={errorCode} />
    </div>
  );
}

function OutcomeField({ label, value }) {
  return (
    <span>
      <span className="font-bold">{`${label}: `}</span>

      {value ?? '--'}
    </span>
  );
}

function Attributes({ attributes }) {
  const entries = Object.entries(attributes ?? {});

  return (
    <div className="flex flex-wrap gap-x-3 font-mono text-xs">
      {entries.map(([key, value]) => <span key={key}>{`${key}=${value}`}</span>)}
    </div>
  );
}

function Trace({ traceId }) {
  if (!traceId) {
    return (
      <Void
        image={<Lucide icon={Unplug} />}
        title="No trace recorded for this request"
      />
    );
  }

  return <LoadedTrace traceId={traceId} />;
}

function LoadedTrace({ traceId }) {
  const { isLoading, isError, isSuccess } = useGetTraceByIdVertical(traceId);

  if (isLoading) {
    return <Skeleton active block />;
  }

  if (isError) {
    return <SomethingWentWrong size="small" />;
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <Board
      header={<SectionTitle size="small" subtitle={traceId} title="Trace" />}
      main={(
        <div className="h-[32rem]">
          <TraceBody traceId={traceId} />
        </div>
      )}
    />
  );
}

export default RequestDetail;
