import { DATE_FORMAT } from '@Src/constants';
import {
  RelativeDateTime,
  Truncate,
} from '@radicalbit/radicalbit-design-system';

const columns = [
  {
    title: '',
    dataIndex: 'margin-left',
    key: 'margin-left',
    width: '10px',
  },

  {
    title: 'Name',
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
    render: (value) => (
      <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
        {value || '--'}
      </Truncate>
    ),
  },

  {
    title: 'Created',
    dataIndex: 'createdAt',
    key: 'createdAt',
    align: 'right',
    sorter: (a, b) => a.createdAt.localeCompare(b.createdAt),
    defaultSortOrder: 'descend',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },

  {
    title: 'Updated',
    dataIndex: 'updatedAt',
    key: 'updatedAt',
    align: 'right',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },

  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },
];

export default columns;
