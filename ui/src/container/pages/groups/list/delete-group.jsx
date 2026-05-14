import SuccessMessage from '@Components/success-message';
import useModals, { modals } from '@Hooks/use-modals';
import { PathsEnum } from '@Src/constants';
import { useGetGroupQuery, useDeleteGroupMutation } from '@State/groups/api';
import { Popconfirm, SectionTitle, TextWithBold } from '@radicalbit/radicalbit-design-system';
import { useMatch, useNavigate } from 'react-router-dom';

function DeleteGroup({ children, uuid }) {
  const { data } = useGetGroupQuery(uuid);
  const routesCount = data?.routes?.length || 0;
  const keysCount = data?.keys?.length || 0;

  if (routesCount || keysCount) {
    return <DeleteGroupModal uuid={uuid}>{children}</DeleteGroupModal>;
  }

  return <DeleteGroupPopconfirm uuid={uuid}>{children}</DeleteGroupPopconfirm>;
}

function DeleteGroupPopconfirm({ children, uuid }) {
  const { data } = useGetGroupQuery(uuid);
  const name = data?.name;

  const match = useMatch(`/${PathsEnum.GROUPS}/:uuid`);
  const currentUuid = match?.params.uuid;
  const navigate = useNavigate();

  const [trigger] = useDeleteGroupMutation({ fixedCacheKey: `delete-group-${uuid}` });

  const handleOnDelete = async () => {
    const { error } = await trigger({
      uuid,
      successMessage: <SuccessMessage prefix="Group" strong={name} suffix="deleted" />,
    });

    if (error) {
      console.error(error);
      return;
    }

    if (currentUuid === uuid) {
      navigate(`/${PathsEnum.GROUPS}`, { replace: true });
    }
  };

  const handleOnCancel = (e) => { e.stopPropagation(); };

  return (
    <Popconfirm
      arrow={false}
      cancelButtonProps={{ type: 'secondary-light' }}
      description={<TextWithBold bold={name} isQuestion text="Are you sure you want to delete the group" />}
      label={children}
      okText={<div className="is-error">Delete</div>}
      okType="error-light"
      onCancel={handleOnCancel}
      onConfirm={handleOnDelete}
      title={<SectionTitle size="small" title="Delete group" titleColor="error" />}
    />
  );
}

function DeleteGroupModal({ children, uuid }) {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.DELETE_GROUP_WITH_ASSOCIATED_ITEMS, { uuid });
  };

  return <div onClick={handleOnClick} role="presentation">{children}</div>;
}

export default DeleteGroup;
