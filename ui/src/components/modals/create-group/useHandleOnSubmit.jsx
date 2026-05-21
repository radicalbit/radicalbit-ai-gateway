import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useCreateGroupMutation } from '@State/groups/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { useCallback } from 'react';

export default () => {
  const { hideModal } = useModals();
  const { isFormInvalid, isDirty, submitForm } = useFormbitContext();

  const [trigger, args] = useCreateGroupMutation({ fixedCacheKey: 'create-group' });
  const isSubmitDisabled = !isDirty || isFormInvalid();

  const handleOnSubmit = useCallback(() => {
    if (isSubmitDisabled || args.isLoading) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const { error: addModelError } = await trigger({
        data: formData,
        successMessage: (<SuccessMessage prefix="Group" strong={formData.name} suffix="created" />),
      });

      if (addModelError) {
        setError('silent.backend', getMessageFromQueryError(addModelError));
        return;
      }

      hideModal();
    });
  }, [args.isLoading, hideModal, isSubmitDisabled, submitForm, trigger]);

  return { handleOnSubmit, args, isSubmitDisabled };
};
