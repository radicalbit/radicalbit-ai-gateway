import useModals from '@Hooks/use-modals';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, Modal } from '@radicalbit/radicalbit-design-system';
import { useState } from 'react';

function Close() {
  const { hideModal } = useModals();

  const { isDirty } = useFormbitContext();

  const [isConfirmingClose, setIsConfirmingClose] = useState(false);

  const handleOnClose = () => {
    if (isDirty) {
      setIsConfirmingClose(true);
      return;
    }

    hideModal();
  };

  const handleOnKeepEditing = () => {
    setIsConfirmingClose(false);
  };

  return (
    <>
      <Button onClick={handleOnClose} type="text">
        Close
      </Button>

      <Modal
        cancelText="Keep editing"
        okText="Discard"
        onCancel={handleOnKeepEditing}
        onOk={hideModal}
        open={isConfirmingClose}
        title="Discard unsaved changes?"
      >
        The configuration has changes that are not saved.
      </Modal>
    </>
  );
}

export default Close;
