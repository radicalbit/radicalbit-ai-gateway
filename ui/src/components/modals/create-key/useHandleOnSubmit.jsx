import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import { useCreateKeyMutation } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';

export default () => {
  const { isFormInvalid, isDirty, submitForm, write } = useFormbitContext();

  const [trigger, args] = useCreateKeyMutation({ fixedCacheKey: 'create-key' });
  const isSubmitDisabled = !isDirty || isFormInvalid();

  const handleOnSubmit = () => {
    if (isSubmitDisabled || args.isLoading) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const { error: addModelError, data } = await trigger({
        data: formData,
        successMessage: (<SuccessMessage prefix="Credential" strong={formData.id} suffix="created" />),
      });

      if (addModelError) {
        setError('silent.backend', getMessageFromQueryError(addModelError));
        return;
      }

      write('__metadata.apiKey', data?.apiKey);
    });
  };

  return { handleOnSubmit, args, isSubmitDisabled };
};
