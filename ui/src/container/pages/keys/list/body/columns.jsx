import HtmlAnchor from '@Components/html-anchor';
import Lucide from '@Components/lucide';
import SuccessMessage from '@Components/success-message';
import useModals, { modals } from '@Hooks/use-modals';
import { DATE_FORMAT, GATEWAY_OWNER, PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import { useRemoveKeyFromGroupMutation } from '@State/groups/api';
import { useGetKeyQuery } from '@State/keys/api';
import {
  DataTableAction,
  Popconfirm,
  RelativeDateTime,
  SectionTitle,
  Skeleton,
  TextWithBold,
  Tooltip, Truncate,
} from '@radicalbit/radicalbit-design-system';
import { Pencil, Plus, Trash2, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import DeleteKey from '../delete-key';

const DISABLED_CREDENTIALS_TOOLTIP = 'This credential is managed externally and cannot be modified';

const columns = [
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },

  {
    title: 'Name',
    dataIndex: 'name',
    key: 'id',
    render: (value) => (
      <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
        <span className="font-[var(--coo-font-weight-bold)]">{value}</span>
      </Truncate>
    ),
  },
  {
    title: 'Owner',
    dataIndex: 'owner',
    key: 'owner',
  },
  {
    title: 'Associated Group',
    dataIndex: 'group',
    align: 'center',
    render: (group) => <AssociatedGroup group={group} />,
  },
  {
    title: 'Created',
    dataIndex: 'createdAt',
    align: 'right',
    sorter: (a, b) => a.createdAt.localeCompare(b.createdAt),
    defaultSortOrder: 'descend',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },
  {
    title: 'Updated',
    dataIndex: 'updatedAt',
    align: 'right',
    key: 'updatedAt',
    render: (date) => <RelativeDateTime format={DATE_FORMAT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },
  {
    title: '',
    dataIndex: 'uuid',
    key: 'uuid',
    render: (uuid) => <DataTableAction><Actions uuid={uuid} /></DataTableAction>,
  },
];

function AssociatedGroup({ group }) {
  const navigate = useNavigate();

  const groupName = group?.name;
  const groupUuid = group?.uuid;

  if (groupName) {
    const handleOnClick = (e) => {
      e.stopPropagation();
      navigate(`/${PathsEnum.GROUPS}/${groupUuid}?${SEARCH_PARAMS.groups}=${encodeURIComponent(groupName)}`);
    };

    return (<HtmlAnchor onClick={handleOnClick}>{groupName}</HtmlAnchor>);
  }

  return '--';
}

function Actions({ uuid }) {
  return (
    <div className="flex">
      <ActionAssociateGroup uuid={uuid} />

      <ActionRemoveGroup uuid={uuid} />

      <ActionEditKey uuid={uuid} />

      <ActionDeleteKey uuid={uuid} />
    </div>
  );
}

function ActionAssociateGroup({ uuid }) {
  const { showModal } = useModals();

  const { data, isLoading, isError, isSuccess } = useGetKeyQuery(uuid);
  const isAssociateGroupDisabled = data?.group;
  const owner = data?.owner;
  const isExternallyManaged = owner !== GATEWAY_OWNER;

  const handleOnAdd = () => {
    showModal(modals.ADD_GROUP_TO_KEY, { uuid });
  };

  if (isLoading) {
    return <Skeleton.Avatar active shape="square" size="small" />;
  }

  if (!isSuccess || isError) {
    return false;
  }

  if (isAssociateGroupDisabled) {
    return false;
  }

  if (isExternallyManaged) {
    return (
      <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}>
        <span>
          <Lucide className="px-4" icon={Plus} />
        </span>
      </Tooltip>
    );
  }

  return (
    <Tooltip title="Associate group">
      <Lucide className="px-4" icon={Plus} onClick={handleOnAdd} />
    </Tooltip>
  );
}

function ActionRemoveGroup({ uuid }) {
  const { data, isLoading, isError, isSuccess } = useGetKeyQuery(uuid);
  const groupName = data?.group?.name;
  const groupUuid = data?.group?.uuid;
  const owner = data?.owner;
  const isExternallyManaged = owner !== GATEWAY_OWNER;

  const [trigger] = useRemoveKeyFromGroupMutation({ fixedCacheKey: `remove-key-${uuid}-from-group-${groupUuid}` });

  const handleOnDelete = async () => {
    const { error } = await trigger({
      uuid: groupUuid,
      keyUUID: uuid,
      successMessage: <SuccessMessage prefix="Group" strong={groupName} suffix="removed" />,
    });

    if (error) {
      console.error(error);
    }
  };

  const handleOnCancel = (e) => { e.stopPropagation(); };

  if (isLoading) {
    return <Skeleton.Avatar active shape="square" size="small" />;
  }

  if (!groupName || !isSuccess || isError) {
    return false;
  }

  if (isExternallyManaged) {
    return (
      <div className="flex">
        <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}>
          <span>
            <Lucide className="px-4" icon={Trash2} />
          </span>
        </Tooltip>
      </div>
    );
  }

  return (
    <div className="flex">
      <Tooltip title="Remove group">
        <Popconfirm
          cancelButtonProps={{ type: 'secondary-light' }}
          description={<TextWithBold bold={groupName} isQuestion text="Are you sure you want to remove the credential from the group" />}
          label={<Lucide className="px-4" icon={X} />}
          okText={<div className="is-error">Remove</div>}
          okType="error-light"
          onCancel={handleOnCancel}
          onConfirm={handleOnDelete}
          title={<SectionTitle size="small" title="Remove group" titleColor="error" />}
        />
      </Tooltip>
    </div>
  );
}

function ActionEditKey({ uuid }) {
  const { showModal } = useModals();

  const { data, isLoading, isError, isSuccess } = useGetKeyQuery(uuid);
  const owner = data?.owner;
  const isExternallyManaged = owner !== GATEWAY_OWNER;

  const handleOnEditKey = () => {
    showModal(modals.EDIT_KEY, { uuid });
  };

  if (isLoading) {
    return <Skeleton.Avatar active shape="square" size="small" />;
  }

  if (!isSuccess || isError) {
    return false;
  }

  if (isExternallyManaged) {
    return (
      <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}>
        <span>
          <Lucide className="px-4" icon={Pencil} />
        </span>
      </Tooltip>
    );
  }

  return (
    <Tooltip title="Edit credential">
      <Lucide className="px-4" icon={Pencil} onClick={handleOnEditKey} />
    </Tooltip>
  );
}

function ActionDeleteKey({ uuid }) {
  const { data, isLoading, isError, isSuccess } = useGetKeyQuery(uuid);
  const owner = data?.owner;
  const isExternallyManaged = owner !== GATEWAY_OWNER;

  if (isLoading) {
    return <Skeleton.Avatar active shape="square" size="small" />;
  }

  if (!isSuccess || isError) {
    return false;
  }

  if (isExternallyManaged) {
    return (
      <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}>
        <span>
          <Lucide className="px-4" icon={Trash2} />
        </span>
      </Tooltip>
    );
  }

  return (
    <DeleteKey uuid={uuid}>
      <Tooltip title="Delete credential">
        <Lucide className="px-4" icon={Trash2} />
      </Tooltip>
    </DeleteKey>
  );
}

export default columns;
