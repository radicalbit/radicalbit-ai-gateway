import { useFormbitContext } from '@radicalbit/formbit';
import { Button } from '@radicalbit/radicalbit-design-system';
import { useState } from 'react';
import useHandleOnSubmit from './useHandleOnSubmit';

function Actions() {
  const { write } = useFormbitContext();

  // Which of the two create buttons was pressed, so only that one shows the spinner
  const [isEnabling, setIsEnabling] = useState(false);

  const { handleOnSubmit, isSubmitDisabled, isLoading } = useHandleOnSubmit();

  const isCreating = isLoading && !isEnabling;
  const isCreatingAndEnabling = isLoading && isEnabling;

  const handleOnBack = () => {
    write('__metadata.step', 1);
  };

  const handleOnCreate = () => {
    setIsEnabling(false);
    handleOnSubmit({ enabled: false });
  };

  const handleOnCreateAndEnable = () => {
    setIsEnabling(true);
    handleOnSubmit({ enabled: true });
  };

  return (
    <div className="flex justify-between w-full">
      <Button onClick={handleOnBack}>Back</Button>

      <div className="flex gap-2">
        <Button
          disabled={isSubmitDisabled}
          loading={isCreating}
          onClick={handleOnCreate}
        >
          Create rule
        </Button>

        <Button
          disabled={isSubmitDisabled}
          loading={isCreatingAndEnabling}
          onClick={handleOnCreateAndEnable}
          type="primary"
        >
          Create rule and enable
        </Button>
      </div>
    </div>
  );
}

export default Actions;
