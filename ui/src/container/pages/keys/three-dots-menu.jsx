import { GATEWAY_OWNER } from '@Src/constants';
import DeleteKey from '@Container/pages/keys/list/delete-key';
import useModals, { modals } from '@Hooks/use-modals';
import { faEllipsisVertical } from '@fortawesome/free-solid-svg-icons';
import {
  Button, Dropdown, FontAwesomeIcon,
  Skeleton,
  Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';
import { useGetKeyQuery } from '@State/keys/api';

function ThreeDotsMenu() {
  const { uuid } = useParams();
  const items = useGetThreeDotsMenuItems(uuid);

  return (
    <Dropdown menu={{ items }}>
      <Button type="text">
        <FontAwesomeIcon icon={faEllipsisVertical} />
      </Button>
    </Dropdown>

  );
}

const DISABLED_CREDENTIALS_TOOLTIP = 'This credential is managed externally and cannot be modified';

export const useGetThreeDotsMenuItems = (uuid) => {
  const { showModal } = useModals();

  const { data, isLoading, isError, isSuccess } = useGetKeyQuery(uuid, { skip: !uuid });

  const associateGroupItem = useGetAssociateGroupItem(uuid);

  const handleOnEditKey = () => {
    showModal(modals.EDIT_KEY, { uuid });
  };

  if (!uuid) {
    return [];
  }

  if (isLoading || !isSuccess || isError) {
    return [];
  }

  const isExternallyManaged = data?.owner !== GATEWAY_OWNER;

  if (isExternallyManaged) {
    return [
      {
        label: <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}>Edit credential</Tooltip>,
        disabled: true,
      },
      {
        type: 'divider',
      },
      {
        label: <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}>Associate group</Tooltip>,
        disabled: true,
      },
      {
        type: 'divider',
      },
      {
        label: <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}><div className="is-error">Delete credential</div></Tooltip>,
        disabled: true,
      },
    ];
  }

  return [
    {
      label: 'Edit credential',
      onClick: handleOnEditKey,
    },
    {
      type: 'divider',
    },
    associateGroupItem,
    {
      type: 'divider',
    },
    {
      label: (
        <DeleteKey uuid={uuid}>
          <div className="is-error">Delete credential</div>
        </DeleteKey>),
    },
  ];
};

const useGetAssociateGroupItem = (uuid) => {
  const { showModal } = useModals();

  const { data, isLoading, isError, isSuccess } = useGetKeyQuery(uuid, { skip: !uuid });
  const isAssociateGroupDisabled = data?.group;

  const handleOnAssociate = () => {
    showModal(modals.ADD_GROUP_TO_KEY, { uuid });
  };

  if (isLoading) {
    return {
      label: <Skeleton.Input active block />,
    };
  }

  if (isError) {
    return {
      label: <Tooltip title="Something went wrong"><div>Associate group</div></Tooltip>,
      disabled: true,
    };
  }

  if (isAssociateGroupDisabled) {
    return {
      label: <Tooltip title="This credential is already associated with a group"><div>Associate group</div></Tooltip>,
      disabled: isAssociateGroupDisabled,
    };
  }

  if (isSuccess) {
    return {
      label: 'Associate group',
      onClick: handleOnAssociate,
    };
  }

  return {
    label: 'Associate group',
  };
};

export default ThreeDotsMenu;
