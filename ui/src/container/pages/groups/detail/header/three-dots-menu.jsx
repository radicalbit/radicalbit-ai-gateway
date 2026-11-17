import Lucide from '@Components/lucide';
import useModals, { modals } from '@Hooks/use-modals';
import { GATEWAY_OWNER } from '@Src/constants';
import { useGetGroupQuery } from '@State/groups/api';
import {
  Button, Dropdown, Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical } from 'lucide-react';
import { useParams } from 'react-router-dom';
import { useRef, useState } from 'react';

const MENU_TRIGGER = ['click'];

function ThreeDotsMenu() {
  const buttonRef = useRef(null);

  const [isOpenedByKeyboard, setIsOpenedByKeyboard] = useState(false);

  const { uuid } = useParams();
  const items = useGetThreeDotsMenuItems(uuid);

  const handleOnOpenChange = (isOpen) => {
    const { activeElement } = document;
    const isFocusLost = activeElement === document.body || activeElement?.closest('.ant-dropdown');

    if (!isOpen) {
      setIsOpenedByKeyboard(false);
    }

    if (!isOpen && isFocusLost) {
      buttonRef.current?.focus();
    }
  };

  const handleOnKeyDown = (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      setIsOpenedByKeyboard(true);
    }
  };

  return (
    <Tooltip title="More actions">
      <Dropdown autoFocus={isOpenedByKeyboard} destroyOnHidden menu={{ items }} onOpenChange={handleOnOpenChange} trigger={MENU_TRIGGER}>
        <Button aria-label="More actions" onKeyDown={handleOnKeyDown} ref={buttonRef} type="text">
          <Lucide icon={EllipsisVertical} />
        </Button>
      </Dropdown>
    </Tooltip>

  );
}

export const useGetThreeDotsMenuItems = (uuid) => {
  const { showModal } = useModals();
  const { data, isLoading, isError, isSuccess } = useGetGroupQuery(uuid, { skip: !uuid });
  const isExternallyManaged = data?.owner !== GATEWAY_OWNER;
  const hasCredentials = !!data?.keys?.length;

  const handleOnAssociateRoutes = () => {
    showModal(modals.ADD_ROUTES_TO_GROUP, { uuid });
  };

  const handleOnDeleteGroup = () => {
    showModal(modals.DELETE_GROUP_WITH_ASSOCIATED_ITEMS, { uuid });
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

  const applyLimitsItem = hasCredentials
    ? { label: 'Apply limits to credentials', onClick: handleOnApplyLimits }
    : { label: <Tooltip title="Add at least one credential: limits are applied to the credentials in the group, not to the group">Apply limits to credentials</Tooltip>, disabled: true };

  if (isExternallyManaged) {
    return [
      {
        label: <Tooltip title="This group is managed externally and cannot be modified">Edit group</Tooltip>,
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
        label: <Tooltip title="This group is managed externally and cannot be modified">Associate credentials</Tooltip>,
        disabled: true,
      },
      applyLimitsItem,
      {
        type: 'divider',
      },
      {
        label: <Tooltip title="This group is managed externally and cannot be modified"><div className="is-error">Delete group</div></Tooltip>,
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
      label: <div className="is-error">Delete group</div>,
      onClick: handleOnDeleteGroup,
    },
  ];
};

export default ThreeDotsMenu;
