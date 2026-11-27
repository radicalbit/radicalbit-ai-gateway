import { formatBlockedBy, formatLimitCategory, formatWindowSeconds } from '@Components/limits/helpers';
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
    title: 'Blocked by',
    key: 'limitScope',
    ellipsis: true,
    render: (_, event) => formatBlockedBy(event),
  },
  {
    title: 'Category',
    dataIndex: 'category',
    key: 'category',
    render: (value) => formatLimitCategory(value),
  },
  {
    title: 'Window',
    dataIndex: 'windowSeconds',
    key: 'windowSeconds',
    render: (value) => formatWindowSeconds(value),
  },
  {
    title: 'Credential',
    dataIndex: 'apiKeyName',
    key: 'apiKeyName',
    ellipsis: true,
  },
];

export default columns;
