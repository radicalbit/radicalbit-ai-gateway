import Lucide from '@Components/lucide';
import { CopyToClipboard } from '@radicalbit/radicalbit-design-system';
import { Copy } from 'lucide-react';

const columns = [
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
];

export default columns;
