import Lucide from '@Components/lucide';
import {
  Button, DataTableAction, Tooltip, Truncate,
} from '@radicalbit/radicalbit-design-system';
import {
  CircleCheck, CircleX, TriangleAlert, Trash,
} from 'lucide-react';
import DeleteAlert from '../delete-alert';

const columns = [
  {
    title: '',
    dataIndex: 'disabledReason',
    key: 'disabledReason',
    width: '40px',
    align: 'center',
    render: (disabledReason) => <DisabledReason disabledReason={disabledReason} />,
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
    render: (enabled) => <Enabled enabled={enabled} />,
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
  },
  {
    title: 'Project',
    dataIndex: 'project',
    key: 'project',
    render: (value) => value ?? '--',
  },
  {
    title: 'Route',
    dataIndex: 'route',
    key: 'route',
    render: (value) => value ?? '--',
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

  return (
    <DataTableAction noHide>
      <span onClick={handleOnClick} role="presentation">
        <DeleteAlert name={name} uuid={uuid}>
          <Button size="small" type="text">
            <Lucide icon={Trash} type="error" />
          </Button>
        </DeleteAlert>
      </span>
    </DataTableAction>
  );
}

function Enabled({ enabled }) {
  if (enabled) {
    return (
      <Tooltip title="Enabled">
        <span className="is-success">
          <Lucide icon={CircleCheck} />
        </span>
      </Tooltip>
    );
  }

  return (
    <Tooltip title="Disabled">
      <span className="opacity-50">
        <Lucide icon={CircleX} />
      </span>
    </Tooltip>
  );
}

function DisabledReason({ disabledReason }) {
  if (!disabledReason) {
    return false;
  }

  return (
    <Tooltip title={disabledReason}>
      <span className="is-error">
        <Lucide icon={TriangleAlert} />
      </span>
    </Tooltip>
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
