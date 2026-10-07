import Lucide from '@Components/lucide';
import { CopyToClipboard } from '@radicalbit/radicalbit-design-system';
import { Copy } from 'lucide-react';
import Status from './status';
import UsedIn from './used-in';

const columns = [
  {
    title: 'Secret key',
    dataIndex: 'key',
    key: 'key',
    render: (value, { status }) => (
      <div className="flex items-center gap-2">
        <CopyToClipboard link={value} modifier="inline-flex w-fit gap-2 items-center" tooltip={{ mouseEnterDelay: 0 }}>
          <span className="font-[var(--coo-font-weight-bold)]">{value}</span>

          <Lucide icon={Copy} />
        </CopyToClipboard>

        <Status status={status} />
      </div>
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
