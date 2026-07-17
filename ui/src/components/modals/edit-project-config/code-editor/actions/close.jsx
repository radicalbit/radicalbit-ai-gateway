import useModals from '@Hooks/use-modals';
import { Button } from '@radicalbit/radicalbit-design-system';

function Close() {
  const { hideModal } = useModals();

  const handleOnClose = () => {
    hideModal();
  };

  return (
    <Button onClick={handleOnClose} type="text">
      Close
    </Button>
  );
}

export default Close;
