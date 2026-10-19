// PROTOTYPE (AG-1041) — List variant B, "Second line under the name": the expiry subtitle gets a
// rotation line below it ("Previous value works until …", orange in the last 24h, or a green "Rotated on …").
import { CredentialStateEnum, GATEWAY_OWNER } from '@Src/constants';
import { SectionTitle, Tooltip, Truncate } from '@radicalbit/radicalbit-design-system';
import classNames from 'classnames';
import dayjs from 'dayjs';
import baseColumns from '../columns';
import { RotationStateEnum, formatInstant } from './mock-rotation';

const EXPIRES_ON_TOOLTIP = 'Expires at end of day (UTC)';

function ExpiresOn({ expiresOn, owner, state }) {
  if (owner !== GATEWAY_OWNER) {
    return false;
  }

  if (!expiresOn) {
    return 'Never expires';
  }

  const date = dayjs(expiresOn).format('DD MMM YYYY');
  const isExpired = state === CredentialStateEnum.EXPIRED;
  const label = isExpired ? `Expired on ${date}` : `Expires on ${date}`;
  const className = classNames({
    'text-[var(--coo-warning)]': state === CredentialStateEnum.EXPIRING,
    'text-[var(--coo-error)]': isExpired,
  });

  return (
    <Tooltip placement="topLeft" title={EXPIRES_ON_TOOLTIP}>
      <span className={className}>{label}</span>
    </Tooltip>
  );
}

function RotationLine({ graceEndsAt, lastRotatedAt, rotationState }) {
  if (rotationState === RotationStateEnum.ROTATED) {
    return <span className="text-[var(--coo-success)]">{`Rotated on ${formatInstant(lastRotatedAt)}`}</span>;
  }

  if (rotationState === RotationStateEnum.IN_GRACE || rotationState === RotationStateEnum.GRACE_ENDING) {
    const className = classNames({ 'text-[var(--coo-warning)]': rotationState === RotationStateEnum.GRACE_ENDING });

    return <span className={className}>{`Previous value works until ${formatInstant(graceEndsAt)}`}</span>;
  }

  return false;
}

function Name({ record }) {
  const {
    expiresOn, graceEndsAt, lastRotatedAt, name, owner, rotationState, state,
  } = record;
  const className = classNames({ 'line-through': state === CredentialStateEnum.EXPIRED });

  return (
    <SectionTitle
      size="small"
      subtitle={(
        <div className="flex flex-col">
          <ExpiresOn expiresOn={expiresOn} owner={owner} state={state} />

          <RotationLine graceEndsAt={graceEndsAt} lastRotatedAt={lastRotatedAt} rotationState={rotationState} />
        </div>
      )}
      title={<Truncate tooltip={{ title: name, placement: 'topLeft' }}><span className={className}>{name}</span></Truncate>}
    />
  );
}

const columnsB = baseColumns.map((column) => (column.key === 'id'
  ? { ...column, render: (_, record) => <Name record={record} /> }
  : column));

export default columnsB;
