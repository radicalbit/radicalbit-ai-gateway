import Lucide from '@Components/lucide';
import SuccessMessage from '@Components/success-message';
import { GATEWAY_OWNER } from '@Src/constants';
import DeleteKey from '@Container/pages/keys/list/delete-key';
// PROTOTYPE (AG-1034): fake expiry until the API returns it
import { EXPIRED_TOOLTIP, getMockExpiry } from '@Container/pages/keys/list/body/prototype-expiry/mock-expiry';
import useModals, { modals } from '@Hooks/use-modals';
import { useRemoveKeyFromGroupMutation } from '@State/groups/api';
import {
  Button, Dropdown,
  Popconfirm,
  SectionTitle,
  Skeleton,
  TextWithBold,
  Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical } from 'lucide-react';
import { useParams } from 'react-router-dom';
import { useGetKeyQuery } from '@State/keys/api';

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

const DISABLED_CREDENTIALS_TOOLTIP = 'This credential is managed externally and cannot be modified';

const UNAVAILABLE_TOOLTIP = 'Unable to load the latest data, please retry later';

export const useGetThreeDotsMenuItems = (uuid) => {
  const { showModal } = useModals();

  const { data, isLoading, isError, isSuccess } = useGetKeyQuery(uuid, { skip: !uuid });

  const associateGroupItem = useGetAssociateGroupItem(uuid);
  const removeGroupItem = useGetRemoveGroupItem(uuid);

  const handleOnEditKey = () => {
    showModal(modals.EDIT_KEY, { uuid });
  };

  if (!uuid) {
    return [];
  }

  if (isError) {
    return [
      {
        label: <Tooltip title={UNAVAILABLE_TOOLTIP}>Unable to load credential</Tooltip>,
        disabled: true,
      },
    ];
  }

  if (isLoading || !isSuccess) {
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

  // PROTOTYPE (AG-1034): an expired credential is delete-only
  const isExpired = getMockExpiry(uuid).state === 'expired';

  if (isExpired) {
    return [
      {
        label: <Tooltip title={EXPIRED_TOOLTIP}>Edit credential</Tooltip>,
        disabled: true,
      },
      {
        type: 'divider',
      },
      {
        label: <Tooltip title={EXPIRED_TOOLTIP}>{data?.group ? 'Remove group' : 'Associate group'}</Tooltip>,
        disabled: true,
      },
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
  }

  return [
    {
      label: 'Edit credential',
      onClick: handleOnEditKey,
    },
    {
      type: 'divider',
    },
    data?.group ? removeGroupItem : associateGroupItem,
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

const useGetRemoveGroupItem = (uuid) => {
  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const groupName = data?.group?.name;
  const groupUuid = data?.group?.uuid;

  const [trigger] = useRemoveKeyFromGroupMutation({ fixedCacheKey: `remove-key-${uuid}-from-group-${groupUuid}` });

  const handleOnRemove = async () => {
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

  return {
    label: (
      <Popconfirm
        arrow={false}
        cancelButtonProps={{ type: 'secondary-light' }}
        description={<TextWithBold bold={groupName} isQuestion text="Are you sure you want to remove the credential from the group" />}
        label={<div>Remove group</div>}
        okText={<div className="is-error">Remove</div>}
        okType="error-light"
        onCancel={handleOnCancel}
        onConfirm={handleOnRemove}
        title={<SectionTitle size="small" title="Remove group" titleColor="error" />}
      />
    ),
  };
};

export default ThreeDotsMenu;
