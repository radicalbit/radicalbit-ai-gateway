import HtmlAnchor from '@Components/html-anchor';
import Lucide from '@Components/lucide';
import SuccessMessage from '@Components/success-message';
import useModals, { modals } from '@Hooks/use-modals';
import { DATE_FORMAT, GATEWAY_OWNER, PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import { useRemoveKeyFromGroupMutation } from '@State/groups/api';
import { useGetKeyQuery } from '@State/keys/api';
import {
  Button,
  DataTableAction,
  Popconfirm,
  RelativeDateTime,
  SectionTitle,
  Skeleton,
  TextWithBold,
  Tooltip, Truncate,
} from '@radicalbit/radicalbit-design-system';
import { PencilLine, Plus, Trash, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import DeleteKey from '../delete-key';

const DISABLED_CREDENTIALS_TOOLTIP = 'This credential is managed externally and cannot be modified';
const NO_GROUPS_TOOLTIP = 'No groups are available to associate';

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
    render: (uuid) => <DataTableAction noHide><Actions uuid={uuid} /></DataTableAction>,
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
    <div className="flex justify-center items-center">
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
    return <IsLoadingAction />;
  }

  if (!isSuccess || isError) {
    return false;
  }

  if (isAssociateGroupDisabled) {
    return (
      <Tooltip title={NO_GROUPS_TOOLTIP}>
        <div>
          <Button disabled size="small" type="text">
            <Lucide icon={Plus} />
          </Button>
        </div>
      </Tooltip>
    );
  }

  if (isExternallyManaged) {
    return (
      <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}>
        <div>
          <Button disabled size="small" type="text">
            <Lucide icon={Plus} />
          </Button>
        </div>
      </Tooltip>
    );
  }

  return (
    <Tooltip title="Associate group">
      <Button onClick={handleOnAdd} size="small" type="text">
        <Lucide icon={Plus} />
      </Button>
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
    return <IsLoadingAction />;
  }

  if (!groupName || !isSuccess || isError) {
    return false;
  }

  if (isExternallyManaged) {
    return (
      <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}>
        <div>
          <Button disabled size="small" type="text">
            <Lucide icon={X} />
          </Button>
        </div>
      </Tooltip>
    );
  }

  return (
    <Tooltip title="Remove group">
      <Popconfirm
        cancelButtonProps={{ type: 'secondary-light' }}
        description={<TextWithBold bold={groupName} isQuestion text="Are you sure you want to remove the credential from the group" />}
        label={(
          <Button size="small" type="text">
            <Lucide icon={X} />
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

function ActionEditKey({ uuid }) {
  const { showModal } = useModals();

  const { data, isLoading, isError, isSuccess } = useGetKeyQuery(uuid);
  const owner = data?.owner;
  const isExternallyManaged = owner !== GATEWAY_OWNER;

  const handleOnEditKey = () => {
    showModal(modals.EDIT_KEY, { uuid });
  };

  if (isLoading) {
    return <IsLoadingAction />;
  }

  if (!isSuccess || isError) {
    return false;
  }

  if (isExternallyManaged) {
    return (
      <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}>
        <div>
          <Button disabled size="small" type="text">
            <Lucide icon={PencilLine} />
          </Button>
        </div>
      </Tooltip>
    );
  }

  return (
    <Tooltip title="Edit credential">
      <Button onClick={handleOnEditKey} size="small" type="text">
        <Lucide icon={PencilLine} />
      </Button>
    </Tooltip>
  );
}

function ActionDeleteKey({ uuid }) {
  const { data, isLoading, isError, isSuccess } = useGetKeyQuery(uuid);
  const owner = data?.owner;
  const isExternallyManaged = owner !== GATEWAY_OWNER;

  if (isLoading) {
    return <IsLoadingAction />;
  }

  if (!isSuccess || isError) {
    return false;
  }

  if (isExternallyManaged) {
    return (
      <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}>
        <div>
          <Button disabled size="small" type="text">
            <Lucide icon={Trash} />
          </Button>
        </div>
      </Tooltip>
    );
  }

  return (
    <DeleteKey uuid={uuid}>
      <Tooltip title="Delete credential">
        <Button size="small" type="text">
          <Lucide icon={Trash} type="error" />
        </Button>
      </Tooltip>
    </DeleteKey>
  );
}

function IsLoadingAction() {
  return (
    <div className="p-4">
      <Skeleton.Avatar active shape="square" size="small" />
    </div>
  );
}

export default columns;
