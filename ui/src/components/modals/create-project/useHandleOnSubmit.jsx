import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useCreateProjectMutation } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { useCallback } from 'react';

export default () => {
  const { hideModal } = useModals();
  const { isFormInvalid, isDirty, submitForm } = useFormbitContext();

  const [trigger, args] = useCreateProjectMutation({ fixedCacheKey: 'create-project' });
  const isSubmitDisabled = !isDirty || isFormInvalid();

  const handleOnSubmit = useCallback(() => {
    if (isSubmitDisabled || args.isLoading) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const { error: createError } = await trigger({
        data: formData,
        successMessage: (<SuccessMessage prefix="Project" strong={formData.name} suffix="created" />),
      });

      if (createError) {
        setError('silent.backend', getMessageFromQueryError(createError));
        return;
      }

      hideModal();
    });
  }, [args.isLoading, hideModal, isSubmitDisabled, submitForm, trigger]);

  return { handleOnSubmit, args, isSubmitDisabled };
};
