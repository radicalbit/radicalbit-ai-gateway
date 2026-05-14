import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useEditKeyMutation } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { useCallback } from 'react';

export default () => {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload.data?.uuid;
  const { isFormInvalid, isDirty, submitForm } = useFormbitContext();

  const [trigger, args] = useEditKeyMutation({ fixedCacheKey: `edit-key-${uuid}` });
  const isSubmitDisabled = !isDirty || isFormInvalid();

  const handleOnSubmit = useCallback(() => {
    if (isSubmitDisabled || args.isLoading) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const { error: editModelError } = await trigger({
        data: formData,
        uuid,
        successMessage: (<SuccessMessage prefix="Credential" strong={formData.name} suffix="updated" />),
      });

      if (editModelError) {
        setError('silent.backend', getMessageFromQueryError(editModelError));
        return;
      }

      hideModal();
    });
  }, [args.isLoading, hideModal, uuid, isSubmitDisabled, submitForm, trigger]);

  return { handleOnSubmit, args, isSubmitDisabled };
};
