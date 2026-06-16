import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals, { modals } from '@Hooks/use-modals';
import { useCreateProjectMutation } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { useCallback } from 'react';

export default () => {
  const { hideModal, showModal } = useModals();
  const { isFormInvalid, isDirty, submitForm } = useFormbitContext();

  const [trigger, args] = useCreateProjectMutation({ fixedCacheKey: 'create-project' });
  const isSubmitDisabled = !isDirty || isFormInvalid();

  const handleOnSubmit = useCallback(() => {
    if (isSubmitDisabled || args.isLoading) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const { error: createError, data } = await trigger({
        data: formData,
        successMessage: (<SuccessMessage prefix="Project" strong={formData.name} suffix="created" />),
      });

      if (createError) {
        setError('silent.backend', getMessageFromQueryError(createError));
        return;
      }

      hideModal();

      if (data?.uuid) {
        showModal(modals.EDIT_PROJECT_CONFIG, { uuid: data.uuid });
      }
    });
  }, [args.isLoading, hideModal, isSubmitDisabled, showModal, submitForm, trigger]);

  return { handleOnSubmit, args, isSubmitDisabled };
};
