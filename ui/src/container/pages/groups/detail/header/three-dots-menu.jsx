import DeleteGroup from '@Container/pages/groups/list/delete-group';
import useModals, { modals } from '@Hooks/use-modals';
import { GATEWAY_OWNER } from '@Src/constants';
import { useGetGroupQuery } from '@State/groups/api';
import { faEllipsisVertical } from '@fortawesome/free-solid-svg-icons';
import {
  Button, Dropdown, FontAwesomeIcon, Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';

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

const DISABLED_GROUP_TOOLTIP = 'This group is managed externally and cannot be modified';

export const useGetThreeDotsMenuItems = (uuid) => {
  const { showModal } = useModals();
  const { data, isLoading, isError, isSuccess } = useGetGroupQuery(uuid, { skip: !uuid });
  const isExternallyManaged = data?.owner !== GATEWAY_OWNER;

  const handleOnAssociateRoutes = () => {
    showModal(modals.ADD_ROUTES_TO_GROUP, { uuid });
  };

  const handleOnAssociateKeys = () => {
    showModal(modals.ADD_KEYS_TO_GROUP, { uuid });
  };

  const handleOnEditKey = () => {
    showModal(modals.EDIT_GROUP, { uuid });
  };

  if (!uuid) {
    return [];
  }

  if (isLoading || !isSuccess || isError) {
    return [];
  }

  if (isExternallyManaged) {
    return [
      {
        label: <Tooltip title={DISABLED_GROUP_TOOLTIP}>Edit group</Tooltip>,
        disabled: true,
      },
      {
        type: 'divider',
      },
      {
        label: 'Associate routes',
        onClick: handleOnAssociateRoutes,
      },
      {
        label: <Tooltip title={DISABLED_GROUP_TOOLTIP}>Associate credentials</Tooltip>,
        disabled: true,
      },
      {
        type: 'divider',
      },
      {
        label: <Tooltip title={DISABLED_GROUP_TOOLTIP}><div className="is-error">Delete group</div></Tooltip>,
        disabled: true,
      },
    ];
  }

  return [
    {
      label: 'Edit group',
      onClick: handleOnEditKey,
    },
    {
      type: 'divider',
    },
    {
      label: 'Associate routes',
      onClick: handleOnAssociateRoutes,
    },
    {
      label: 'Associate credentials',
      onClick: handleOnAssociateKeys,
    },
    {
      type: 'divider',
    },
    {
      label: (
        <DeleteGroup uuid={uuid}>
          <div className="is-error">Delete group</div>
        </DeleteGroup>),
    },
  ];
};

export default ThreeDotsMenu;
