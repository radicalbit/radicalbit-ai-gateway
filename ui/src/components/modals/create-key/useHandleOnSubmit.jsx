import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import { useCreateKeyMutation } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { ExpiryModeEnum } from './schema';

export default () => {
  const { form, isFormInvalid, isDirty, submitForm, write } = useFormbitContext();
  const name = form?.name;
  const expiryMode = form?.expiryMode;
  const expiresOn = form?.expiresOn;

  const [trigger, args] = useCreateKeyMutation({ fixedCacheKey: 'create-key' });
  // Picking an expiry option makes the form dirty, so the name must be checked explicitly
  const isExpiryDateMissing = expiryMode === ExpiryModeEnum.DATE && !expiresOn;
  const isSubmitDisabled = !isDirty || !name || isFormInvalid() || isExpiryDateMissing;

  const handleOnSubmit = () => {
    if (isSubmitDisabled || args.isLoading) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      // With Never, send null even if the hidden picker still holds a date
      const { error: addModelError, data } = await trigger({
        data: {
          name: formData.name,
          expiresOn: formData.expiryMode === ExpiryModeEnum.DATE ? formData.expiresOn : null,
        },
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
