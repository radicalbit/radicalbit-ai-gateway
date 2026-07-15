import Channel from '@Container/pages/alerts/detail/body/form-fields/channel';
import Recipient from '@Container/pages/alerts/detail/body/form-fields/recipient';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, FormField } from '@radicalbit/radicalbit-design-system';
import Enabled from './enabled';
import useHandleOnSubmit from './useHandleOnSubmit';

function StepC() {
  const { error } = useFormbitContext();
  const backendError = error('silent.backend');

  return (
    <div className="flex flex-col gap-4">
      <strong>Channel and recipient</strong>

      <Channel />

      <Recipient />

      <div className="pt-4" />

      <Enabled />

      {backendError ? <FormField message={backendError} /> : false}

      <Actions />
    </div>
  );
}

function Actions() {
  const { write } = useFormbitContext();
  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  const handleOnBack = () => {
    write('__metadata.step', 1);
  };

  return (
    <div className="flex justify-between">
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

export default StepC;
