import Lucide from '@Components/lucide';
import { CopyToClipboard, Tooltip } from '@radicalbit/radicalbit-design-system';
import { SecretStatusEnum } from '@Src/constants';
import { Copy } from 'lucide-react';
import Status from './status';
import UsedIn from './used-in';

const columns = [
  {
    title: 'Secret key',
    dataIndex: 'key',
    key: 'key',
    render: (value, { status }) => <SecretKey status={status} value={value} />,
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
      <Tooltip title="Unavailable: a published configuration references this key, but the secrets backend no longer holds it">
        <div className="inline-flex items-center gap-2">
          <span className="font-[var(--coo-font-weight-bold)] text-[var(--coo-text-tertiary)]">{value}</span>

          <Status status={status} />
        </div>
      </Tooltip>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <CopyToClipboard link={value} tooltip={{ mouseEnterDelay: 0 }}>
        <div className="flex items-center gap-2">
          <span className="font-[var(--coo-font-weight-bold)]">{value}</span>

          <Lucide icon={Copy} />
        </div>
      </CopyToClipboard>

      <Status status={status} />
    </div>
  );
}

export default columns;
