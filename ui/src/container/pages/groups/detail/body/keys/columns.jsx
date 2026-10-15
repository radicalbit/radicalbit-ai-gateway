import Lucide from '@Components/lucide';
import SuccessMessage from '@Components/success-message';
import {
  CredentialStateEnum, DATE_FORMAT, DATE_FORMAT_SHORT, GATEWAY_OWNER,
} from '@Src/constants';
import { useGetGroupQuery, useRemoveKeyFromGroupMutation } from '@State/groups/api';
import {
  Button,
  DataTableAction,
  Popconfirm, RelativeDateTime, SectionTitle, Skeleton, TextWithBold,
  Tooltip,
  Truncate,
} from '@radicalbit/radicalbit-design-system';
import classNames from 'classnames';
import dayjs from 'dayjs';
import { Trash } from 'lucide-react';
import { useParams } from 'react-router-dom';

const EXPIRES_ON_TOOLTIP = 'Expires at end of day (UTC)';

const columns = [
  {
    title: 'Name',
    dataIndex: 'name',
    width: '40%',
    key: 'id',
    render: (value, { expiresOn, owner, state }) => <Name expiresOn={expiresOn} name={value} owner={owner} state={state} />,
  },
  {
    title: 'Created',
    dataIndex: 'createdAt',
    align: 'right',
    width: '15%',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },
  {
    title: 'Updated',
    dataIndex: 'updatedAt',
    align: 'right',
    width: '15%',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },
  {
    title: '',
    dataIndex: 'uuid',
    align: 'uuid',
    width: '10%',
    render: (uuid, record) => <DataTableAction noHide><Actions record={record} uuid={uuid} /></DataTableAction>,
  },
];

const DISABLED_GROUP_TOOLTIP = 'This group is managed externally and cannot be modified';

function Name({ expiresOn, name, owner, state }) {
  const className = classNames({ 'line-through': state === CredentialStateEnum.EXPIRED });

  return (
    <SectionTitle
      size="small"
      subtitle={<ExpiresOn expiresOn={expiresOn} owner={owner} state={state} />}
      title={(
        <Truncate tooltip={{ title: name, placement: 'topLeft' }}>
          <span className={className}>{name}</span>
        </Truncate>
      )}
    />
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

function Actions({ uuid: keyUUID, record: { name } }) {
  const { uuid } = useParams();
  const { data: groupData, isLoading, isError, isSuccess } = useGetGroupQuery(uuid);
  const isExternallyManaged = groupData?.owner !== GATEWAY_OWNER;

  const [trigger] = useRemoveKeyFromGroupMutation({ fixedCacheKey: `remove-key-${keyUUID}-from-group-${uuid}` });

  const handleOnDelete = async () => {
    const { error } = await trigger({
      uuid,
      keyUUID,
      successMessage: <SuccessMessage prefix="Group" strong={name} suffix="removed" />,
    });

    if (error) {
      console.error(error);
    }
  };

  const handleOnCancel = (e) => { e.stopPropagation(); };

  // The click is handled by the wrapping Popconfirm: the handler only keeps the Button clickable
  const handleOnTriggerClick = () => {};

  if (isLoading) {
    return <Skeleton.Avatar active shape="square" size="small" />;
  }

  if (!isSuccess || isError) {
    return false;
  }

  if (isExternallyManaged) {
    return (
      <Tooltip title={DISABLED_GROUP_TOOLTIP}>
        <div>
          <Button aria-label="Remove" disabled size="small" type="text">
            <Lucide disabled icon={Trash} />
          </Button>
        </div>
      </Tooltip>
    );
  }

  return (
    <Tooltip title="Remove">
      <Popconfirm
        cancelButtonProps={{ type: 'secondary-light' }}
        description={<TextWithBold bold={name} isQuestion text="Are you sure you want to remove the group from the credential" />}
        label={(
          <Button aria-label="Remove" onClick={handleOnTriggerClick} size="small" type="text">
            <Lucide icon={Trash} type="error" />
          </Button>
          )}
        okText={<div className="is-error">Remove</div>}
        okType="error-light"
        onCancel={handleOnCancel}
        onConfirm={handleOnDelete}
        title={<SectionTitle size="small" title="Remove group" titleColor="error" />}
      />
    </Tooltip>
  );
}

export default columns;
