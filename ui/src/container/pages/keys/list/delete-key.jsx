import SuccessMessage from '@Components/success-message';
import useModals, { modals } from '@Hooks/use-modals';
import { useGetKeyQuery, useDeleteKeyMutation } from '@State/keys/api';
import { Popconfirm, SectionTitle, TextWithBold } from '@radicalbit/radicalbit-design-system';

function DeleteKey({ children, uuid }) {
  const { data } = useGetKeyQuery(uuid);
  const group = data?.group;

  if (group) {
    return <DeleteKeyModal uuid={uuid}>{children}</DeleteKeyModal>;
  }

  return <DeleteKeyPopconfirm uuid={uuid}>{children}</DeleteKeyPopconfirm>;
}

function DeleteKeyPopconfirm({ children, uuid }) {
  const { data } = useGetKeyQuery(uuid);
  const name = data?.name;

  const [trigger] = useDeleteKeyMutation({ fixedCacheKey: `delete-key-${uuid}` });

  const handleOnDelete = async () => {
    const { error } = await trigger({
      uuid,
      successMessage: <SuccessMessage prefix="Credential" strong={name} suffix="deleted" />,
    });

    if (error) {
      console.error(error);
    }
  };

  const handleOnCancel = (e) => { e.stopPropagation(); };

  return (
    <Popconfirm
      arrow={false}
      cancelButtonProps={{ type: 'secondary-light' }}
      description={<TextWithBold bold={name} isQuestion text="Are you sure you want to delete the credential" />}
      label={children}
      okText={<div className="is-error">Delete</div>}
      okType="error-light"
      onCancel={handleOnCancel}
      onConfirm={handleOnDelete}
      title={<SectionTitle size="small" title="Delete credential" titleColor="error" />}
    />
  );
}

function DeleteKeyModal({ children, uuid }) {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.DELETE_KEY_WITH_GROUPS, { uuid });
  };

  return <div onClick={handleOnClick} role="presentation">{children}</div>;
}

export default DeleteKey;
