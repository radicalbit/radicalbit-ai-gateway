import Description from '@Container/pages/alerts/detail/body/form-fields/description';
import Name from '@Container/pages/alerts/detail/body/form-fields/name';
import useModals from '@Hooks/use-modals';
import { Button } from '@radicalbit/radicalbit-design-system';
import useHandleOnNext from './useHandleOnNext';

function StepA() {
  return (
    <div className="flex flex-col gap-4">
      <Name />

      <Description />

      <Actions />
    </div>
  );
}

function Actions() {
  const { hideModal } = useModals();
  const { handleOnNext } = useHandleOnNext();

  return (
    <div className="flex justify-between">
      <Button onClick={hideModal}>Close</Button>

      <Button onClick={handleOnNext} type="primary">Next</Button>
    </div>
  );
}

export default StepA;
