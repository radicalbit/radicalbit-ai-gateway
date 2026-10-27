import Lucide from '@Components/lucide';
import DeleteGroup from '@Container/pages/groups/list/delete-group';
import useModals, { modals } from '@Hooks/use-modals';
import { GATEWAY_OWNER } from '@Src/constants';
import { useGetGroupQuery } from '@State/groups/api';
import {
  Button, Dropdown, Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical } from 'lucide-react';
import { useParams } from 'react-router-dom';

function ThreeDotsMenu() {
  const { uuid } = useParams();
  const items = useGetThreeDotsMenuItems(uuid);

  return (
    <Tooltip title="More actions">
      <Dropdown menu={{ items }}>
        <Button aria-label="More actions" type="text">
          <Lucide icon={EllipsisVertical} />
        </Button>
      </Dropdown>
    </Tooltip>

  );
}

const DISABLED_GROUP_TOOLTIP = 'This group is managed externally and cannot be modified';

// Limits are copied onto the credentials in the group: an empty group has nobody to copy them to
const NO_CREDENTIALS_TOOLTIP = 'Add at least one credential: limits are applied to the credentials in the group, not to the group';

export const useGetThreeDotsMenuItems = (uuid) => {
  const { showModal } = useModals();
  const { data, isLoading, isError, isSuccess } = useGetGroupQuery(uuid, { skip: !uuid });
  const isExternallyManaged = data?.owner !== GATEWAY_OWNER;
  const hasCredentials = !!data?.keys?.length;

  const handleOnAssociateRoutes = () => {
    showModal(modals.ADD_ROUTES_TO_GROUP, { uuid });
  };

  const handleOnAssociateKeys = () => {
    showModal(modals.ADD_KEYS_TO_GROUP, { uuid });
  };

  const handleOnApplyLimits = () => {
    showModal(modals.APPLY_GROUP_LIMITS, { uuid });
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

  // Enabled on externally managed groups too: the limits land on each credential
  const applyLimitsItem = hasCredentials
    ? { label: 'Apply limits to credentials', onClick: handleOnApplyLimits }
    : { label: <Tooltip title={NO_CREDENTIALS_TOOLTIP}>Apply limits to credentials</Tooltip>, disabled: true };

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
      applyLimitsItem,
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
    applyLimitsItem,
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
