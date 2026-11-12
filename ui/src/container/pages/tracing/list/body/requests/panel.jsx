import HtmlAnchor from '@Components/html-anchor';
import InfoPopover from '@Components/info-popover';
import Lucide from '@Components/lucide';
import useModals, { modals } from '@Hooks/use-modals';
import { formatInt, formatMs } from '@Src/helpers/column-formatters';
import formatCost from '@Src/helpers/format-cost';
import { useGetRequestByIdVertical, useGetRequestsWithRange } from '@State/requests/vertical-hooks';
import {
  Board,
  Button,
  Skeleton,
  Tag,
  TextWithBold,
  Timeline,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { REQUESTS_PAGE_PARAM, SELECTED_REQUEST_PARAM } from './constants';
import { CredentialLink, GroupLink } from './entity-links';
import { formatOffset, requestSteps, selectedRequestUuid } from './helpers';

const VISIBLE_TAGS = 3;

const LABEL_PROPS = { type: 'secondary' };

const STATUS_PROPS = {
  handled_error: { type: 'error' },
  unhandled_error: { type: 'error' },
};

function RequestPanel() {
  const [searchParams] = useSearchParams();
  const page = Number(searchParams.get(REQUESTS_PAGE_PARAM)) || 1;
  const requestUuid = searchParams.get(SELECTED_REQUEST_PARAM);

  const { data: requestsData } = useGetRequestsWithRange({ page });
  const items = requestsData?.items ?? [];

  const selectedUuid = selectedRequestUuid(items, requestUuid);

  const { currentData, isError, isFetching, isSuccess, refetch } = useGetRequestByIdVertical(selectedUuid);

  const isLoading = isFetching && !currentData;

  if (isLoading) {
    return <Board main={<Skeleton active block />} width="100%" />;
  }

  if (isError) {
    return <IsError isFetching={isFetching} refetch={refetch} />;
  }

  if (!isSuccess || !currentData) {
    return false;
  }

  return (
    <section aria-label="Selected request" className="flex flex-col gap-4">
      <Summary request={currentData} />

      <StepByStep request={currentData} />
    </section>
  );
}

function Summary({ request }) {
  const apiKeyName = request?.apiKeyName;
  const cost = request?.cost;
  const durationMs = request?.durationMs;
  const errorType = request?.errorType;
  const groupName = request?.groupName;
  const groupUuid = request?.groupUuid;
  const httpStatusCode = request?.httpStatusCode;
  const requestStatus = request?.requestStatus;
  const tags = request?.tags ?? [];
  const totalTokens = request?.totalTokens;

  const statusLine = [httpStatusCode, errorType].filter(Boolean).join(' · ');
  const statusProps = STATUS_PROPS[requestStatus];
  const tokens = totalTokens ? formatInt(totalTokens) : '--';

  return (
    <div className="flex flex-wrap items-center gap-x-7 gap-y-2">
      <TextWithBold bold={statusLine} boldProps={statusProps} text="Status" textProps={LABEL_PROPS} />

      <TextWithBold bold={<CredentialLink apiKeyName={apiKeyName} />} text="Credential" textProps={LABEL_PROPS} />

      <TextWithBold bold={<GroupLink groupName={groupName} groupUuid={groupUuid} />} text="Group" textProps={LABEL_PROPS} />

      <TextWithBold bold={<SummaryTags tags={tags} />} text="Tags" textProps={LABEL_PROPS} />

      <TextWithBold bold={formatMs(durationMs)} text="Duration" textProps={LABEL_PROPS} />

      <TextWithBold bold={tokens} text="Tokens" textProps={LABEL_PROPS} />

      <TextWithBold bold={formatCost(cost)} text="Cost" textProps={LABEL_PROPS} />
    </div>
  );
}

function SummaryTags({ tags }) {
  const visibleTags = tags.slice(0, VISIBLE_TAGS);
  const hiddenCount = tags.length - visibleTags.length;

  if (tags.length === 0) {
    return '--';
  }

  if (hiddenCount === 0) {
    return (
      <span className="inline-flex flex-wrap items-center gap-1">
        {visibleTags.map((tag) => <Tag key={tag} type="secondary">{tag}</Tag>)}
      </span>
    );
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {visibleTags.map((tag) => <Tag key={tag} type="secondary">{tag}</Tag>)}

      <InfoPopover
        content={(
          <div className="flex flex-col gap-1">
            {tags.map((tag) => <Tag key={tag} type="secondary">{tag}</Tag>)}
          </div>
        )}
        title="Tags"
      >
        <Tag rounded type="secondary">{`+${hiddenCount}`}</Tag>
      </InfoPopover>
    </span>
  );
}

function StepByStep({ request }) {
  const steps = requestSteps(request);
  const eventCount = steps.length - 1;
  const eventLabel = eventCount === 1 ? '· 1 event' : `· ${eventCount} events`;

  const items = steps.map(({
    blocking, fields, key, offsetMs, tone, type,
  }) => ({
    key,
    tone,
    title: formatOffset(offsetMs),
    content: <Step blocking={blocking} fields={fields} type={type} />,
  }));

  return (
    <Board
      footer={<TraceLink request={request} />}
      header={<TextWithBold bold={eventLabel} boldProps={LABEL_PROPS} text={<strong>Step by step</strong>} />}
      main={<Timeline items={items} mode="start" titleSpan={3} />}
      width="100%"
    />
  );
}

function Step({ blocking, fields, type }) {
  return (
    <div className="flex flex-col gap-1.5">
      <StepTitle blocking={blocking} type={type} />

      <div className="flex flex-wrap gap-1">
        {fields.map(({ name, value }) => (
          <Tag key={name} type="secondary">
            {`${name} `}

            <strong>{value}</strong>
          </Tag>
        ))}
      </div>
    </div>
  );
}

function StepTitle({ blocking, type }) {
  if (blocking) {
    return (
      <div className="flex items-center gap-2">
        <strong className="font-mono">{type}</strong>

        <Tag type="error">blocking</Tag>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <strong className="font-mono">{type}</strong>
    </div>
  );
}

function TraceLink({ request }) {
  const { showModal } = useModals();

  const traceId = request?.traceId;

  const handleOnClick = () => {
    showModal(modals.TRACE_DETAIL, { traceId });
  };

  if (!traceId) {
    return <span>No trace recorded for this request.</span>;
  }

  return <HtmlAnchor onClick={handleOnClick}>Open request detail and trace</HtmlAnchor>;
}

function IsError({ isFetching, refetch }) {
  return (
    <Board
      main={(
        <Void
          actions={<Button loading={isFetching} onClick={refetch}>Retry</Button>}
          description="This might be temporary, please retry later"
          image={<Lucide icon={TriangleAlert} />}
          size="small"
          title="Unable to load the request"
        />
      )}
      width="100%"
    />
  );
}

export default RequestPanel;
