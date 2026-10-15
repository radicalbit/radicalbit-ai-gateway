// PROTOTYPE (AG-1034) — Variant C, "No new column": expiry lives under the name as a subtitle,
// with a small badge next to the name for expiring / expired. Quietest option.
import { SectionTitle, Tag, Tooltip, Truncate } from '@radicalbit/radicalbit-design-system';
import {
  actionsColumn, createdColumn, groupColumn, marginColumn, ownerColumn, updatedColumn,
} from './actions-menu';
import { EXPIRY_TOOLTIP, formatExpiresOn } from './mock-expiry';

function NameCell({ name, expiresOn, state }) {
  const subtitle = (() => {
    if (!expiresOn) return <span style={{ opacity: 0.6 }}>Never expires</span>;
    if (state === 'expired') return <span style={{ color: 'var(--coo-error)' }}>{`Expired on ${formatExpiresOn(expiresOn)}`}</span>;
    if (state === 'expiring') return <span style={{ color: 'var(--coo-warning)' }}>{`Expires on ${formatExpiresOn(expiresOn)}`}</span>;
    return <span style={{ opacity: 0.6 }}>{`Expires on ${formatExpiresOn(expiresOn)}`}</span>;
  })();

  const badge = {
    expiring: <Tag size="small" type="warning-light">Expiring</Tag>,
    expired: <Tag size="small" type="error-light">Expired</Tag>,
  }[state];

  return (
    <SectionTitle
      size="small"
      subtitle={<Tooltip placement="topLeft" title={expiresOn ? EXPIRY_TOOLTIP : undefined}>{subtitle}</Tooltip>}
      title={(
        <div className="flex items-center gap-2">
          <Truncate tooltip={{ title: name, placement: 'topLeft' }}>
            <span style={state === 'expired' ? { textDecoration: 'line-through' } : undefined}>{name}</span>
          </Truncate>

          {badge}
        </div>
      )}
    />
  );
}

const columnsC = [
  marginColumn('margin-left'),
  {
    title: 'Name',
    dataIndex: 'name',
    key: 'id',
    render: (name, { expiresOn, state }) => <NameCell expiresOn={expiresOn} name={name} state={state} />,
  },
  ownerColumn,
  groupColumn,
  createdColumn,
  updatedColumn,
  actionsColumn,
  marginColumn('margin-right'),
];

export default columnsC;
