import Lucide from '@Components/lucide';
import { CopyToClipboard } from '@radicalbit/radicalbit-design-system';
import { SecretStatusEnum } from '@Src/constants';
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
        <SecretKey status={status} value={value} />

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

function SecretKey({ status, value }) {
  if (status === SecretStatusEnum.UNAVAILABLE) {
    return (
      <span className="font-[var(--coo-font-weight-bold)] text-[var(--coo-text-tertiary)]">{value}</span>
    );
  }

  return (
    <CopyToClipboard link={value} tooltip={{ mouseEnterDelay: 0 }}>
      <div className="flex items-center gap-2">
        <span className="font-[var(--coo-font-weight-bold)]">{value}</span>

        <Lucide icon={Copy} />
      </div>
    </CopyToClipboard>
  );
}

export default columns;
