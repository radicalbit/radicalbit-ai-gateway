import HtmlAnchor from '@Components/html-anchor';
import SuccessMessage from '@Components/success-message';
import useModals, { modals } from '@Hooks/use-modals';
import { DATE_FORMAT, GATEWAY_OWNER, PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import { useRemoveKeyFromGroupMutation } from '@State/groups/api';
import { useGetKeyQuery } from '@State/keys/api';
import {
  faEdit, faPlus, faTrash,
} from '@fortawesome/free-solid-svg-icons';
import {
  DataTableAction,
  FontAwesomeIcon,
  Popconfirm,
  RelativeDateTime,
  SectionTitle,
  Skeleton,
  TextWithBold,
  Tooltip, Truncate,
} from '@radicalbit/radicalbit-design-system';
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
          <FontAwesomeIcon className="px-4" disabled icon={faPlus} />
        </span>
      </Tooltip>
    );
  }

  return (
    <Tooltip title="Associate group">
      <FontAwesomeIcon className="px-4" icon={faPlus} onClick={handleOnAdd} />
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
            <FontAwesomeIcon className="px-4" disabled icon={faTrash} />
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
          label={<FontAwesomeIcon className="px-4" icon={faTrash} />}
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
          <FontAwesomeIcon className="px-4" disabled icon={faEdit} />
        </span>
      </Tooltip>
    );
  }

  return (
    <Tooltip title="Edit credential">
      <FontAwesomeIcon className="px-4" icon={faEdit} onClick={handleOnEditKey} />
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
          <FontAwesomeIcon className="px-4" disabled icon={faTrash} />
        </span>
      </Tooltip>
    );
  }

  return (
    <DeleteKey uuid={uuid}>
      <Tooltip title="Delete credential">
        <FontAwesomeIcon className="px-4" icon={faTrash} />
      </Tooltip>
    </DeleteKey>
  );
}

export default columns;
