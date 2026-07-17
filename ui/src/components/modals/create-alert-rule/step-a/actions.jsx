import useModals from '@Hooks/use-modals';
import { Button } from '@radicalbit/radicalbit-design-system';
import useHandleOnNext from './useHandleOnNext';

function Actions() {
  const { hideModal } = useModals();
  const { handleOnNext } = useHandleOnNext();

  return (
    <div className="flex justify-between w-full">
      <Button onClick={hideModal}>Close</Button>

      <Button onClick={handleOnNext} type="primary">Next</Button>
    </div>
  );
}

export default Actions;
