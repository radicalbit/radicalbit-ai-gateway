import { useFormbitContext } from '@radicalbit/formbit';
import { Button } from '@radicalbit/radicalbit-design-system';
import useHandleOnNext from './useHandleOnNext';

function Actions() {
  const { write } = useFormbitContext();
  const { handleOnNext } = useHandleOnNext();

  const handleOnBack = () => {
    write('__metadata.step', 0);
  };

  return (
    <div className="flex justify-between w-full">
      <Button onClick={handleOnBack}>Back</Button>

      <Button onClick={handleOnNext} type="primary">Next</Button>
    </div>
  );
}

export default Actions;
