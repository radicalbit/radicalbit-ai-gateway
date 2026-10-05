import Lucide from '@Components/lucide';
import { CopyToClipboard } from '@radicalbit/radicalbit-design-system';
import { Copy } from 'lucide-react';
import Status from './status';
import UsedIn from './used-in';

const columns = [
  {
    title: '',
    dataIndex: 'status',
    key: 'status',
    width: '48px',
    render: (status) => <Status status={status} />,
  },
  {
    title: 'Secret key',
    dataIndex: 'key',
    key: 'key',
    render: (value) => (
      <CopyToClipboard link={value} modifier="flex gap-2 items-center" tooltip={{ mouseEnterDelay: 0 }}>
        <span className="font-[var(--coo-font-weight-bold)]">{value}</span>

        <Lucide icon={Copy} />
      </CopyToClipboard>
    ),
  },
  {
    title: 'Used in projects',
    dataIndex: 'usedIn',
    key: 'usedIn',
    render: (usedIn) => <UsedIn usedIn={usedIn} />,
  },
];

export default columns;
