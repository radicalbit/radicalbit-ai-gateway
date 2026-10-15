// PROTOTYPE (AG-1034) — Variant B, "Separate state column": Status tag + plain Expires date.
// Expired rows are greyed out as a whole (see onRow in index.jsx).
import { Tag, Tooltip } from '@radicalbit/radicalbit-design-system';
import {
  actionsColumn, createdColumn, groupColumn, marginColumn, nameColumn, ownerColumn,
} from './actions-menu';
import { EXPIRY_TOOLTIP, formatExpiresOn } from './mock-expiry';

const STATE_TAG = {
  active: { label: 'Active', type: 'success-outlined' },
  expiring: { label: 'Expiring', type: 'warning-outlined' },
  expired: { label: 'Expired', type: 'error-outlined' },
};

const columnsB = [
  marginColumn('margin-left'),
  nameColumn,
  {
    title: 'Status',
    dataIndex: 'state',
    key: 'state',
    filters: Object.entries(STATE_TAG).map(([value, { label }]) => ({ text: label, value })),
    onFilter: (value, record) => record.state === value,
    render: (state) => <Tag rounded size="large" type={STATE_TAG[state].type}>{STATE_TAG[state].label}</Tag>,
  },
  ownerColumn,
  groupColumn,
  {
    title: 'Expires',
    dataIndex: 'expiresOn',
    key: 'expiresOn',
    align: 'right',
    sorter: (a, b) => (a.expiresOn ?? '9999').localeCompare(b.expiresOn ?? '9999'),
    render: (expiresOn) => (expiresOn
      ? <Tooltip title={EXPIRY_TOOLTIP}><span>{formatExpiresOn(expiresOn)}</span></Tooltip>
      : 'Never'),
  },
  createdColumn,
  actionsColumn,
  marginColumn('margin-right'),
];

export const rowStyleB = ({ state }) => (state === 'expired' ? { opacity: 0.45 } : undefined);

export default columnsB;
