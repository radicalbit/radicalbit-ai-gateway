import HtmlAnchor from '@Components/html-anchor';
import InfoPopover from '@Components/info-popover';
import {
  CredentialStateEnum, DATE_FORMAT_SHORT, GATEWAY_OWNER, PathsEnum, ROTATION_FORMAT, RotationStateEnum, SEARCH_PARAMS,
} from '@Src/constants';
import { Tooltip } from '@radicalbit/radicalbit-design-system';
import classNames from 'classnames';
import dayjs from 'dayjs';
import { useNavigate } from 'react-router-dom';

const EXPIRES_ON_TOOLTIP = 'Expires at end of day (UTC)';

function Keys({ keys }) {
  return (
    <InfoPopover content={<PopoverContent keys={keys} />} minWidth="200" title={<strong>Credentials</strong>}>
      {keys.length}
    </InfoPopover>
  );
}

function PopoverContent({ keys }) {
  const navigate = useNavigate();

  if (!keys || keys.length === 0) {
    return (
      <div style={{ maxHeight: 200, overflowY: 'auto' }}>
        --
      </div>
    );
  }

  return (
    <div style={{ maxHeight: 200, overflowY: 'auto' }}>
      {keys.map((key) => {
        const handleOnClick = (e) => {
          e.stopPropagation();
          navigate(`/${PathsEnum.CREDENTIALS}?${SEARCH_PARAMS.credentials}=${encodeURIComponent(key.name)}`);
        };

        const className = classNames({ 'line-through': key.state === CredentialStateEnum.EXPIRED });

        return (
          <div key={key.uuid} className="flex flex-col pb-2">
            <HtmlAnchor onClick={handleOnClick}>
              <span className={className}>{key.name}</span>
            </HtmlAnchor>

            <span className="text-xs">
              <ExpiresOn expiresOn={key.expiresOn} owner={key.owner} state={key.state} />
            </span>

            <span className="text-xs">
              <Rotation graceEndsAt={key.graceEndsAt} lastRotatedAt={key.lastRotatedAt} owner={key.owner} rotationState={key.rotationState} />
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ExpiresOn({ expiresOn, owner, state }) {
  // Externally managed credentials have no expiry: their lifecycle stays with the identity provider
  if (owner !== GATEWAY_OWNER) {
    return false;
  }

  if (!expiresOn) {
    return 'Never expires';
  }

  // expiresOn is a calendar date: dayjs parses YYYY-MM-DD as a local date, so no timezone shift
  const date = dayjs(expiresOn).format(DATE_FORMAT_SHORT.trim());
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

function Rotation({ graceEndsAt, lastRotatedAt, owner, rotationState }) {
  const isGraceEnding = rotationState === RotationStateEnum.GRACE_ENDING;
  const isGraceRunning = rotationState === RotationStateEnum.IN_GRACE || isGraceEnding;
  const className = classNames({ 'text-[var(--coo-warning)]': isGraceEnding });

  // Externally managed credentials are never rotated: their lifecycle stays with the identity provider
  if (owner !== GATEWAY_OWNER) {
    return false;
  }

  if (rotationState === RotationStateEnum.ROTATED) {
    return <span className="text-[var(--coo-success)]">{`Rotated on ${dayjs(lastRotatedAt).format(ROTATION_FORMAT)}`}</span>;
  }

  if (isGraceRunning) {
    return <span className={className}>{`Previous value works until ${dayjs(graceEndsAt).format(ROTATION_FORMAT)}`}</span>;
  }

  return false;
}

export default Keys;
