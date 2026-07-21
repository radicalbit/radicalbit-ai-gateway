import HtmlAnchor from '@Components/html-anchor';
import Lucide from '@Components/lucide';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import {
  FormatBold,
  formatInt,
  formatMs,
  formatText,
  formatTimestamp,
} from '@Src/helpers/column-formatters';
import { Button, Tooltip } from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

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

const columns = [
  {
    title: 'Route',
    dataIndex: 'routeName',
    align: 'left',
    render: (value, { traceStatus }) => (
      <StatusTooltip traceStatus={traceStatus}>
        <div className="flex items-center gap-2">
          <FormatBold value={value} />

          <Status traceStatus={traceStatus} />
        </div>
      </StatusTooltip>
    ),
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
    title: 'Spans',
    dataIndex: 'totalSpans',
    align: 'right',
    render: formatInt,
  },
  {
    title: 'Errors',
    dataIndex: 'errorCount',
    align: 'right',
    render: formatInt,
  },
  {
    title: 'Total Tokens',
    dataIndex: 'totalTokens',
    align: 'right',
    render: formatInt,
  },
  {
    title: 'Created At',
    dataIndex: 'createdAt',
    align: 'right',
    render: formatTimestamp,
  },
  {
    title: 'Latest Span',
    dataIndex: 'latestSpanTs',
    align: 'right',
    render: formatTimestamp,
  },
];

function StatusTooltip({ traceStatus, children }) {
  switch (traceStatus) {
    case 'error': return (
      <Tooltip title="Status: error">
        {children}
      </Tooltip>
    );

    case 'warning': return (
      <Tooltip title="Status: warning">
        {children}
      </Tooltip>
    );

    default: return (
      <Tooltip title="Status: success">
        {children}
      </Tooltip>
    );
  }
}

function Status({ traceStatus }) {
  switch (traceStatus) {
    case 'error': return (
      <Button className="capitalize" shape="circle" size="small" type="error">
        <Lucide icon={TriangleAlert} />
      </Button>
    );

    case 'warning': return (
      <Button className="capitalize" shape="circle" size="small" type="warning-light">
        <Lucide icon={TriangleAlert} />
      </Button>
    );

    default: return '';
  }
}

export default columns;
