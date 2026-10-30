import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useDeleteProjectMutation, useGetProjectQuery } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { useCallback } from 'react';

export default () => {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload.data?.uuid;
  const { submitForm } = useFormbitContext();

  const { data } = useGetProjectQuery(uuid);
  const name = data?.name;

  const [trigger, args] = useDeleteProjectMutation({ fixedCacheKey: `delete-project-${uuid}` });

  const handleOnSubmit = useCallback(() => {
    if (args.isLoading) {
      return;
    }

    submitForm(async (_, setError) => {
      const { error } = await trigger({
        uuid,
        successMessage: (<SuccessMessage prefix="Project" strong={name} suffix="deleted" />),
      });

      if (error) {
        setError('silent.backend', getMessageFromQueryError(error));
        return;
      }

      localStorage.removeItem('rbit-gw-projectUuid');
      hideModal();
    });
  }, [args.isLoading, hideModal, submitForm, trigger, uuid, name]);

  return { handleOnSubmit, args };
};
