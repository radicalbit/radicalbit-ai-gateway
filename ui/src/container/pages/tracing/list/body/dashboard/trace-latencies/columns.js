import { formatMs } from '@Src/helpers/column-formatters';

const columns = [
  {
    title: '',
    dataIndex: 'foo',
    width: 600,
  },
  {
    title: 'p50',
    dataIndex: 'p50',
    align: 'right',
    render: formatMs,
  },
  {
    title: 'p90',
    dataIndex: 'p90',
    align: 'right',
    render: formatMs,
  },
  {
    title: 'p95',
    dataIndex: 'p95',
    align: 'right',
    render: formatMs,
  },
  {
    title: 'p99',
    dataIndex: 'p99',
    align: 'right',
    render: formatMs,
  },
];

export default columns;
