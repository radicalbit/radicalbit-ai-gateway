import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useGetKeyQuery, useRotateKeyMutation } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { getBoundsError, getExpiryInstant, getGracePeriod } from './grace-period';

// A bounds violation comes back in the request-validation shape, not in the error envelope;
// pydantic prefixes its messages with "Value error, "
const getRotationErrorMessage = (queryError) => {
  const validationMessage = queryError?.data?.detail?.[0]?.msg;

  if (validationMessage) {
    return validationMessage.replace(/^Value error, /, '');
  }

  return getMessageFromQueryError(queryError);
};

export default () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form, isFormInvalid, submitForm, write } = useFormbitContext();

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const name = data?.name;
  const expiresOn = data?.expiresOn;

  const [trigger, args] = useRotateKeyMutation({ fixedCacheKey: `rotate-key-${uuid}` });

  const boundsError = getBoundsError(form, getExpiryInstant(expiresOn));
  const isSubmitDisabled = isFormInvalid() || !!boundsError || args.isLoading;

  const handleOnSubmit = () => {
    if (isSubmitDisabled) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const { error, data: rotated } = await trigger({
        uuid,
        data: { gracePeriod: getGracePeriod(formData) },
        successMessage: <SuccessMessage prefix="Credential" strong={name} suffix="rotated" />,
      });

      if (error) {
        setError('silent.backend', getRotationErrorMessage(error));
        return;
      }

      write('__metadata.apiKey', rotated?.apiKey);
    });
  };

  return {
    handleOnSubmit, args, isSubmitDisabled, boundsError,
  };
};
