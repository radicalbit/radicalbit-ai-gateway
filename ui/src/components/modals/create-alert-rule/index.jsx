import useModals from '@Hooks/use-modals';
import {
  RbitModal, SectionTitle,
} from '@radicalbit/radicalbit-design-system';

function CreateAlertRule() {
  const { hideModal } = useModals();

  return (
    <RbitModal
      closable
      header={(
        <SectionTitle
          title="Create Alert"
          titleColor="primary"
        />
      )}
      onCancel={hideModal}
      open
      width={400}
    />
  );
}

export default CreateAlertRule;
