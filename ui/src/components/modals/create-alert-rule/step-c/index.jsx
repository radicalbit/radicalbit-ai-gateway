import Channel from '@Container/pages/alerts/detail/body/form-fields/channel';
import Recipient from '@Container/pages/alerts/detail/body/form-fields/recipient';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField } from '@radicalbit/radicalbit-design-system';

function StepC() {
  const { error } = useFormbitContext();
  const backendError = error('silent.backend');

  return (
    <div className="flex flex-col gap-4">
      <strong>Channel and recipient</strong>

      <Channel />

      <Recipient />

      {backendError ? <FormField message={backendError} /> : false}
    </div>
  );
}

export default StepC;
