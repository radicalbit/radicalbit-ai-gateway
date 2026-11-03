import EventIcon from '@Components/event-icon';
import HtmlAnchor from '@Components/html-anchor';
import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import {
  FormatBold,
  formatCost,
  formatInt,
  formatMs,
  formatText,
  formatTimestamp,
} from '@Src/helpers/column-formatters';
import { Tooltip } from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import RequestTypeCell from './request-type-cell';
import TagsCell from './tags-cell';

function AssociatedGroup({ groupName, groupUuid }) {
  const navigate = useNavigate();

  if (groupName) {
    const handleOnClick = (e) => {
      e.stopPropagation();
      navigate(`/${PathsEnum.GROUPS}/${groupUuid}?${SEARCH_PARAMS.groups}=${encodeURIComponent(groupName)}`);
    };

    return (<HtmlAnchor className="p-4" onClick={handleOnClick}>{groupName}</HtmlAnchor>);
  }

  return '--';
}

// One column per event icon: lit only when that kind of event fired in the
// request (AG-1108), whatever the route configures.
const eventIconColumn = (title, kind, dataIndex) => ({
  title,
  dataIndex,
  key: dataIndex,
  align: 'center',
  width: '50px',
  render: (fired) => <div className="flex justify-center"><EventIcon fired={Boolean(fired)} kind={kind} /></div>,
});

const columns = [
  {
    title: 'Route',
    dataIndex: 'routeName',
    align: 'left',
    render: (value, { requestStatus }) => (
      <StatusTooltip requestStatus={requestStatus}>
        <div className="flex items-center gap-2">
          <FormatBold value={value} />

          <Status requestStatus={requestStatus} />
        </div>
      </StatusTooltip>
    ),
  },
  {
    title: 'Type',
    dataIndex: 'requestType',
    align: 'left',
    render: (requestType) => <RequestTypeCell requestType={requestType} />,
  },
  {
    title: 'Tags',
    dataIndex: 'tags',
    align: 'left',
    render: (tags) => <TagsCell tags={tags} />,
  },
  {
    title: 'Group',
    dataIndex: 'groupName',
    align: 'left',
    render: (groupName, record) => <AssociatedGroup groupName={groupName} groupUuid={record.groupUuid} />,
  },
  {
    title: 'Credential',
    dataIndex: 'apiKeyName',
    align: 'left',
    render: formatText,
  },
  {
    title: 'Duration',
    dataIndex: 'durationMs',
    align: 'right',
    render: formatMs,
  },
  {
    title: 'Errors',
    dataIndex: 'httpStatusCode',
    align: 'left',
    render: (httpStatusCode, { requestStatus, errorType }) => (
      <RequestError errorType={errorType} httpStatusCode={httpStatusCode} requestStatus={requestStatus} />
    ),
  },
  eventIconColumn('Guardrail', 'guardrail', 'hasGuardrail'),
  eventIconColumn('Cache', 'cache', 'hasCacheHit'),
  eventIconColumn('Fallback', 'fallback', 'hasFallback'),
  eventIconColumn('Adv Routing', 'routing', 'hasRouting'),
  eventIconColumn('Limits', 'limits', 'hasLimit'),
  {
    title: 'Total Tokens',
    dataIndex: 'totalTokens',
    align: 'right',
    render: formatInt,
  },
  {
    title: 'Cost',
    dataIndex: 'cost',
    align: 'right',
    render: formatCost,
  },
  {
    title: 'Created At',
    dataIndex: 'createdAt',
    align: 'right',
    render: formatTimestamp,
  },
];

function RequestError({ requestStatus, httpStatusCode, errorType }) {
  if (!requestStatus || requestStatus === 'success') {
    return '--';
  }

  return [httpStatusCode, errorType].filter(Boolean).join(' ') || '--';
}

const STATUS_LABELS = {
  success: 'success',
  handled_error: 'handled error',
  unhandled_error: 'unhandled error',
};

function StatusTooltip({ requestStatus, children }) {
  const label = STATUS_LABELS[requestStatus] ?? STATUS_LABELS.success;

  return (
    <Tooltip title={`Status: ${label}`}>
      {children}
    </Tooltip>
  );
}

function Status({ requestStatus }) {
  switch (requestStatus) {
    case 'unhandled_error': return (
      <IconBadge aria-label="Status: unhandled error" className="capitalize" size="small" type="error">
        <Lucide icon={TriangleAlert} />
      </IconBadge>
    );

    case 'handled_error': return (
      <IconBadge aria-label="Status: handled error" className="capitalize" size="small" type="warning-light">
        <Lucide icon={TriangleAlert} />
      </IconBadge>
    );

    default: return '';
  }
}

export default columns;
