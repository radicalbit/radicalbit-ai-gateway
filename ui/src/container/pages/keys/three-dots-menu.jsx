import Lucide from '@Components/lucide';
import SuccessMessage from '@Components/success-message';
import { CredentialStateEnum, GATEWAY_OWNER, RotationStateEnum } from '@Src/constants';
import DeleteKey from '@Container/pages/keys/list/delete-key';
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
import { useEndGracePeriodMutation, useGetKeyQuery } from '@State/keys/api';

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

const EXPIRED_CREDENTIALS_TOOLTIP = 'This credential has expired: it can only be deleted or removed from its group';

const UNAVAILABLE_TOOLTIP = 'Unable to load the latest data, please retry later';

const IN_GRACE_TOOLTIP = 'A grace period is running: end it before rotating again';

export const useGetThreeDotsMenuItems = (uuid) => {
  const { showModal } = useModals();

  const { data, isLoading, isError, isSuccess } = useGetKeyQuery(uuid, { skip: !uuid });

  const associateGroupItem = useGetAssociateGroupItem(uuid);
  const removeGroupItem = useGetRemoveGroupItem(uuid);
  const endGracePeriodItem = useGetEndGracePeriodItem(uuid);

  const handleOnEditKey = () => {
    showModal(modals.EDIT_KEY, { uuid });
  };

  const handleOnRotateKey = () => {
    showModal(modals.ROTATE_KEY, { uuid });
  };

  const handleOnManageLimits = () => {
    showModal(modals.MANAGE_KEY_LIMITS, { uuid });
  };

  // In every state: externally managed credentials can have limits too, expired ones open read-only
  const manageLimitsItem = {
    label: 'Manage limits',
    onClick: handleOnManageLimits,
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
        label: <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}>Rotate credential</Tooltip>,
        disabled: true,
      },
      {
        type: 'divider',
      },
      {
        label: <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}>Associate group</Tooltip>,
        disabled: true,
      },
      manageLimitsItem,
      {
        type: 'divider',
      },
      {
        label: <Tooltip title={DISABLED_CREDENTIALS_TOOLTIP}><div className="is-error">Delete credential</div></Tooltip>,
        disabled: true,
      },
    ];
  }

  const group = data?.group;
  const state = data?.state;
  const rotationState = data?.rotationState;
  const isGraceRunning = rotationState === RotationStateEnum.IN_GRACE || rotationState === RotationStateEnum.GRACE_ENDING;

  // A credential holds at most two values: no new rotation while the previous value still works
  const rotateItem = isGraceRunning
    ? { label: <Tooltip title={IN_GRACE_TOOLTIP}>Rotate credential</Tooltip>, disabled: true }
    : { label: 'Rotate credential', onClick: handleOnRotateKey };

  // Only while a grace period is running
  const endGraceItem = isGraceRunning ? endGracePeriodItem : false;
  // An expired credential can still leave its group (cleanup), but can't join one
  const expiredGroupItem = group ? removeGroupItem : {
    label: <Tooltip title={EXPIRED_CREDENTIALS_TOOLTIP}>Associate group</Tooltip>,
    disabled: true,
  };

  if (state === CredentialStateEnum.EXPIRED) {
    return [
      {
        label: <Tooltip title={EXPIRED_CREDENTIALS_TOOLTIP}>Edit credential</Tooltip>,
        disabled: true,
      },
      {
        label: <Tooltip title={EXPIRED_CREDENTIALS_TOOLTIP}>Rotate credential</Tooltip>,
        disabled: true,
      },
      {
        type: 'divider',
      },
      expiredGroupItem,
      manageLimitsItem,
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
    rotateItem,
    endGraceItem,
    {
      type: 'divider',
    },
    group ? removeGroupItem : associateGroupItem,
    manageLimitsItem,
    {
      type: 'divider',
    },
    {
      label: (
        <DeleteKey uuid={uuid}>
          <div className="is-error">Delete credential</div>
        </DeleteKey>),
    },
  ].filter(Boolean);
};

const useGetEndGracePeriodItem = (uuid) => {
  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const name = data?.name;

  const [trigger] = useEndGracePeriodMutation({ fixedCacheKey: `end-grace-period-${uuid}` });

  const handleOnEnd = async () => {
    const { error } = await trigger({
      uuid,
      successMessage: <SuccessMessage prefix="Grace period of" strong={name} suffix="ended" />,
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
        description="The previous value stops working now."
        label={<div>End grace period</div>}
        okText={<div className="is-error">End</div>}
        okType="error-light"
        onCancel={handleOnCancel}
        onConfirm={handleOnEnd}
        title={<SectionTitle size="small" title="End grace period" titleColor="error" />}
      />
    ),
  };
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
