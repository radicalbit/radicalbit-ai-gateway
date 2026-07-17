import { useFormbitContext } from '@radicalbit/formbit';
import { Button } from '@radicalbit/radicalbit-design-system';
import useHandleOnSubmit from './useHandleOnSubmit';

function Actions() {
  const { write } = useFormbitContext();
  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  const handleOnBack = () => {
    write('__metadata.step', 1);
  };

  return (
    <div className="flex justify-between w-full">
      <Button onClick={handleOnBack}>Back</Button>

      <Button
        disabled={isSubmitDisabled}
        loading={isLoading}
        onClick={handleOnSubmit}
        type="primary"
      >
        Submit
      </Button>
    </div>
  );
}

export default Actions;
