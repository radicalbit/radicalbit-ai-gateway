import Lucide from '@Components/lucide';
import { CredentialLink, GroupLink } from '@Container/pages/tracing/list/body/requests/entity-links';
import RequestTypeCell from '@Container/pages/tracing/list/body/requests/request-type-cell';
import useModals from '@Hooks/use-modals';
import { formatInt, formatMs, formatTimestamp } from '@Src/helpers/column-formatters';
import formatCost from '@Src/helpers/format-cost';
import { useGetRequestByIdVertical } from '@State/requests/vertical-hooks';
import { useGetTraceByIdVertical } from '@State/tracing/vertical-hooks';
import {
  NewHeader, SectionTitle, Skeleton, Tag, TextWithBold,
} from '@radicalbit/radicalbit-design-system';
import { ArrowLeft } from 'lucide-react';
import useCloseRequestDetail from './use-close-request-detail';

const LABEL_PROPS = { type: 'secondary' };

const STATUS_TAGS = {
  success: 'success',
  handled_error: 'error',
  unhandled_error: 'error',
};

function Header() {
  const { modalPayload } = useModals();
  const requestUuid = modalPayload?.data?.requestUuid;

  const { data, isError, isLoading, isSuccess } = useGetRequestByIdVertical(requestUuid);
  const routeName = data?.routeName;

  if (isLoading) {
    return <NewHeader title={<Skeleton.Input active />} />;
  }

  if (isError) {
    return <NewHeader title={<SectionTitle title="Request detail" titlePrefix={<BackButton />} />} />;
  }

  if (!data) {
    return <NewHeader title={<SectionTitle title="Request detail" titlePrefix={<BackButton />} />} />;
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <NewHeader
      details={{ one: <Summary /> }}
      title={(
        <SectionTitle
          subtitle={<Meta />}
          title={routeName}
          titlePrefix={<BackButton />}
          titleSuffix={<Tags />}
          wrapTitle
        />
      )}
    />
  );
}

function BackButton() {
  const handleOnClose = useCloseRequestDetail();

  return <Lucide aria-label="Back" className="cursor-pointer" icon={ArrowLeft} onClick={handleOnClose} />;
}

function Tags() {
  const { modalPayload } = useModals();
  const requestUuid = modalPayload?.data?.requestUuid;

  const { data } = useGetRequestByIdVertical(requestUuid);
  const errorType = data?.errorType;
  const httpStatusCode = data?.httpStatusCode;
  const requestStatus = data?.requestStatus;
  const requestType = data?.requestType;

  const statusLine = [httpStatusCode, errorType].filter(Boolean).join(' · ');
  const statusTag = STATUS_TAGS[requestStatus] ?? 'secondary';

  return (
    <div className="flex items-center gap-2">
      <Tag type={statusTag}>{statusLine}</Tag>

      <RequestTypeCell requestType={requestType} />
    </div>
  );
}

function Summary() {
  const { modalPayload } = useModals();
  const requestUuid = modalPayload?.data?.requestUuid;

  const { data: request } = useGetRequestByIdVertical(requestUuid);
  const cost = request?.cost;
  const durationMs = request?.durationMs;
  const totalTokens = request?.totalTokens;
  const traceId = request?.traceId;

  const { data: trace } = useGetTraceByIdVertical(traceId);
  const errorCount = trace?.errorCount;
  const totalSpans = trace?.totalSpans;

  const spans = totalSpans === 1 ? '1 span' : `${formatInt(totalSpans)} spans`;
  const errors = errorCount === 1 ? '1 error' : `${formatInt(errorCount)} errors`;
  const tokens = `${formatInt(totalTokens)} tokens`;
  const requestSummary = [formatMs(durationMs), tokens, formatCost(cost)].join(' · ');
  const traceSummary = [formatMs(durationMs), spans, errors, tokens, formatCost(cost)].join(' · ');

  if (!trace) {
    return <span className="text-xs">{requestSummary}</span>;
  }

  return <span className="text-xs">{traceSummary}</span>;
}

function Meta() {
  const { modalPayload } = useModals();
  const requestUuid = modalPayload?.data?.requestUuid;

  const { data } = useGetRequestByIdVertical(requestUuid);
  const apiKeyName = data?.apiKeyName;
  const createdAt = data?.createdAt;
  const groupName = data?.groupName;
  const groupUuid = data?.groupUuid;
  const tags = data?.tags ?? [];
  const traceId = data?.traceId;

  const tagsLine = tags.length ? tags.join(', ') : '--';

  return (
    <div className="flex flex-wrap gap-x-5 gap-y-1">
      <TextWithBold bold={<CredentialLink apiKeyName={apiKeyName} />} size="small" text="Credential" textProps={LABEL_PROPS} />

      <TextWithBold bold={<GroupLink groupName={groupName} groupUuid={groupUuid} />} size="small" text="Group" textProps={LABEL_PROPS} />

      <TextWithBold bold={formatTimestamp(createdAt).trim()} size="small" text="Created" textProps={LABEL_PROPS} />

      <TextWithBold bold={tagsLine} size="small" text="Tags" textProps={LABEL_PROPS} />

      <TextWithBold bold={traceId ?? '--'} size="small" text="Trace" textProps={LABEL_PROPS} />

      <TextWithBold bold={requestUuid} size="small" text="Request" textProps={LABEL_PROPS} />
    </div>
  );
}

export default Header;
