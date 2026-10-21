import useModals from '@Hooks/use-modals';
import {
  CredentialStateEnum, DATE_FORMAT_SHORT, GATEWAY_OWNER, PathsEnum, ROTATION_FORMAT, RotationStateEnum,
} from '@Src/constants';
import Lucide from '@Components/lucide';
import { useGetAssociableKeysByGroupQuery, useGetGroupQuery } from '@State/groups/api';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Alert,
  FormField,
  Select,
  Skeleton,
  Tooltip,
} from '@radicalbit/radicalbit-design-system';
import classNames from 'classnames';
import dayjs from 'dayjs';
import { Search } from 'lucide-react';
import { Link } from 'react-router-dom';

const EXPIRES_ON_TOOLTIP = 'Expires at end of day (UTC)';

function Keys() {
  const { modalPayload } = useModals();
  const groupUuid = modalPayload?.data?.uuid;
  const { data = [], isLoading, isError, isSuccess } = useGetAssociableKeysByGroupQuery({ groupUuid }, { skip: !groupUuid });
  const keys = data.map((i) => ({ label: i.name, value: i.uuid }));

  if (isLoading) {
    return <Skeleton.Input active />;
  }

  if (isError) {
    return 'Something went wrong';
  }

  if (!isSuccess) {
    return false;
  }

  if (keys.length === 0) {
    return (
      <NoKeysAlert />
    );
  }

  return (
    <KeysInner />
  );
}

function KeysInner() {
  const { write } = useFormbitContext();
  const { modalPayload } = useModals();
  const groupUuid = modalPayload?.data?.uuid;
  const { data = [] } = useGetAssociableKeysByGroupQuery({ groupUuid }, { skip: !groupUuid });
  const keys = data.map((i) => ({
    label: i.name,
    value: i.uuid,
    expiresOn: i.expiresOn,
    graceEndsAt: i.graceEndsAt,
    lastRotatedAt: i.lastRotatedAt,
    owner: i.owner,
    rotationState: i.rotationState,
    state: i.state,
  }));

  const handleOnSelect = (value) => {
    write('keys', value);
  };

  const handleOnFilterOption = (input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase());

  // Dropdown options show the expiry and rotation under the name; the selected tags keep just the name
  const handleOnOptionRender = ({ data: option }) => <KeyOption option={option} />;

  return (
    <FormField>
      <Select
        aria-label="Credentials"
        filterOption={handleOnFilterOption}
        mode="multiple"
        onChange={handleOnSelect}
        optionRender={handleOnOptionRender}
        options={keys}
        placeholder={(
          <div className="flex flex-row items-center justify-between gap-4">
            <div>
              Select one or more credentials
            </div>

            <Lucide icon={Search} />
          </div>
        )}
      />
    </FormField>
  );
}

function KeyOption({ option }) {
  const label = option?.label;
  const expiresOn = option?.expiresOn;
  const graceEndsAt = option?.graceEndsAt;
  const lastRotatedAt = option?.lastRotatedAt;
  const owner = option?.owner;
  const rotationState = option?.rotationState;
  const state = option?.state;

  return (
    <div className="flex flex-col">
      <span>{label}</span>

      <span className="text-xs opacity-70">
        <ExpiresOn expiresOn={expiresOn} owner={owner} state={state} />
      </span>

      <span className="text-xs opacity-70">
        <Rotation graceEndsAt={graceEndsAt} lastRotatedAt={lastRotatedAt} owner={owner} rotationState={rotationState} />
      </span>
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

function NoKeysAlert() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetGroupQuery(uuid);
  const name = data?.name;

  return (
    <FormField>
      <Alert
        description={(
          <span>
            {'All the available credentials have been associated with the group '}

            <strong>{name}</strong>

            {'. Please go to the '}

            <Link className="c-anchor light" to={`/${PathsEnum.CREDENTIALS}`}><strong>credentials section</strong></Link>

            {' and create a new credential if needed.'}
          </span>
        )}
        type="info"
      />
    </FormField>
  );
}

export default Keys;
