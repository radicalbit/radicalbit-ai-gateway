import Lucide from '@Components/lucide';
import SuccessMessage from '@Components/success-message';
import { CredentialStateEnum, GATEWAY_OWNER } from '@Src/constants';
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

const EXPIRED_CREDENTIALS_TOOLTIP = 'This credential has expired and can only be deleted';

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

  const group = data?.group;
  const state = data?.state;
  const groupItemLabel = group ? 'Remove group' : 'Associate group';

  if (state === CredentialStateEnum.EXPIRED) {
    return [
      {
        label: <Tooltip title={EXPIRED_CREDENTIALS_TOOLTIP}>Edit credential</Tooltip>,
        disabled: true,
      },
      {
        type: 'divider',
      },
      {
        label: <Tooltip title={EXPIRED_CREDENTIALS_TOOLTIP}>{groupItemLabel}</Tooltip>,
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
    group ? removeGroupItem : associateGroupItem,
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
