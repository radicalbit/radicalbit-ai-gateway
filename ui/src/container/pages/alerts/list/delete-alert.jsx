import SuccessMessage from '@Components/success-message';
import { useDeleteAlertMutation } from '@State/alerts/api';
import { Popconfirm, SectionTitle, TextWithBold } from '@radicalbit/radicalbit-design-system';

function DeleteAlert({ children, uuid, name }) {
  const [trigger] = useDeleteAlertMutation({ fixedCacheKey: `delete-alert-${uuid}` });

  const handleOnDelete = async () => {
    const { error } = await trigger({
      uuid,
      successMessage: <SuccessMessage prefix="Alert rule" strong={name} suffix="deleted" />,
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
      description={<TextWithBold bold={name} isQuestion text="Are you sure you want to delete the alert rule" />}
      label={children}
      okText={<div className="is-error">Delete</div>}
      okType="error-light"
      onCancel={handleOnCancel}
      onConfirm={handleOnDelete}
      title={<SectionTitle size="small" title="Delete alert rule" titleColor="error" />}
    />
  );
}

export default DeleteAlert;
