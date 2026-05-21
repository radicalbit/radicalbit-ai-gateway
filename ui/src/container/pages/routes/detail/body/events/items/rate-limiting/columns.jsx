import dateFormatter from '@Helpers/date-formatter';
import dayjs from 'dayjs';

const columns = [
  {
    title: 'Timestamp',
    dataIndex: 'timestamp',
    key: 'timestamp',
    sorter: (a, b) => dayjs(a.timestamp).unix() - dayjs(b.timestamp).unix(),
    render: (value) => dateFormatter(value),
  },
  {
    title: 'Credential Name',
    dataIndex: 'apiKeyName',
    key: 'apiKeyName',
    ellipsis: true,
  },
];

export default columns;
