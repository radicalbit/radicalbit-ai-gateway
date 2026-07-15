import { faTrash, faWarning } from '@fortawesome/free-solid-svg-icons';
import {
  DataTableAction, FontAwesomeIcon, Tooltip, Truncate,
} from '@radicalbit/radicalbit-design-system';
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
          <FontAwesomeIcon className="px-4" icon={faTrash} />
        </DeleteAlert>
      </span>
    </DataTableAction>
  );
}

function DisabledReason({ disabledReason }) {
  if (!disabledReason) {
    return false;
  }

  return (
    <Tooltip title={disabledReason}>
      <span className="is-error">
        <FontAwesomeIcon icon={faWarning} />
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
