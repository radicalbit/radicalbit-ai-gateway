import Lucide from '@Components/lucide';
import { ALERT_SCOPE_LABELS } from '@Src/constants';
import { useToggleAlertMutation } from '@State/alerts/api';
import { FCK_TOGGLE_ALERT } from '@State/alerts/fixed-cache-key';
import {
  Button, DataTableAction, Switch, Tooltip, Truncate,
} from '@radicalbit/radicalbit-design-system';
import { TriangleAlert, Trash } from 'lucide-react';
import DeleteAlert from '../delete-alert';

const columns = [
  {
    title: '',
    dataIndex: 'staleReason',
    key: 'staleReason',
    width: '40px',
    align: 'center',
    render: (staleReason) => <StaleReason staleReason={staleReason} />,
  },
  {
    title: 'Rule Name',
    dataIndex: 'name',
    key: 'name',
    render: (value) => (
      <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
        <span className="font-[var(--coo-font-weight-bold)]">{value}</span>
      </Truncate>
    ),
  },
  {
    title: 'Active',
    dataIndex: 'enabled',
    key: 'enabled',
    width: '80px',
    align: 'center',
    render: (enabled, record) => <EnabledToggle enabled={enabled} uuid={record.uuid} />,
  },
  {
    title: 'Description',
    dataIndex: 'description',
    key: 'description',
    render: (value) => <Description description={value} />,
  },
  {
    title: 'Recipient',
    dataIndex: 'recipients',
    key: 'recipients',
    render: (recipients) => <Recipients recipients={recipients} />,
  },
  {
    title: 'Scope',
    dataIndex: 'scope',
    key: 'scope',
    render: (value) => ALERT_SCOPE_LABELS[value] ?? value ?? '--',
  },
  {
    title: 'Project',
    dataIndex: 'projectName',
    key: 'projectName',
    render: (value) => value ?? '--',
  },
  {
    title: 'Target',
    dataIndex: 'scope',
    key: 'target',
    render: (_, record) => <Target record={record} />,
  },
  {
    title: 'Event',
    dataIndex: 'event',
    key: 'event',
    render: (value) => value ?? '--',
  },
  {
    title: 'Aggregation',
    dataIndex: 'timeAggregation',
    key: 'timeAggregation',
    render: (value) => value ?? '--',
  },
  {
    title: 'Channel',
    dataIndex: 'channel',
    key: 'channel',
    render: (value) => value ?? '--',
  },
  {
    title: '',
    dataIndex: 'uuid',
    key: 'actions',
    width: '30px',
    render: (uuid, record) => <Actions name={record.name} uuid={uuid} />,
  },
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },
];

function Actions({ uuid, name }) {
  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  // The click is handled by the wrapping Popconfirm: the handler only keeps the Button clickable
  const handleOnTriggerClick = () => {};

  return (
    <DataTableAction noHide>
      <span onClick={handleOnClick} role="presentation">
        <DeleteAlert name={name} uuid={uuid}>
          <Tooltip title="Delete alert rule">
            <Button aria-label="Delete alert rule" onClick={handleOnTriggerClick} size="small" type="text">
              <Lucide icon={Trash} type="error" />
            </Button>
          </Tooltip>
        </DeleteAlert>
      </span>
    </DataTableAction>
  );
}

function EnabledToggle({ enabled, uuid }) {
  const [trigger, { isLoading }] = useToggleAlertMutation({ fixedCacheKey: `${FCK_TOGGLE_ALERT}-${uuid}` });

  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  const handleOnChange = (checked) => {
    trigger({ uuid, enabled: checked });
  };

  if (enabled) {
    return (
      <span onClick={handleOnClick} role="presentation">
        <Tooltip title="Disable alert rule">
          <Switch aria-label="Disable alert rule" checked loading={isLoading} onChange={handleOnChange} size="small" />
        </Tooltip>
      </span>
    );
  }

  return (
    <span onClick={handleOnClick} role="presentation">
      <Tooltip title="Enable alert rule">
        <Switch aria-label="Enable alert rule" checked={false} loading={isLoading} onChange={handleOnChange} size="small" />
      </Tooltip>
    </span>
  );
}

function StaleReason({ staleReason }) {
  if (!staleReason) {
    return false;
  }

  return (
    <Tooltip title={staleReason}>
      <span>
        <Lucide icon={TriangleAlert} type="warning" />
      </span>
    </Tooltip>
  );
}

// The route, project or credential the rule watches, according to its scope
function Target({ record }) {
  const targetByScope = {
    route: record.route,
    project: record.projectName,
    credential: record.credentialName,
  };
  const value = targetByScope[record.scope];

  if (!value) {
    return '--';
  }

  return (
    <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
      {value}
    </Truncate>
  );
}

function Description({ description }) {
  if (!description) {
    return '--';
  }

  return (
    <Truncate tooltip={{ title: description, placement: 'topLeft' }}>
      {description}
    </Truncate>
  );
}

function Recipients({ recipients }) {
  const value = (recipients ?? []).join(', ');

  if (!value) {
    return '--';
  }

  return (
    <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
      {value}
    </Truncate>
  );
}

export default columns;
