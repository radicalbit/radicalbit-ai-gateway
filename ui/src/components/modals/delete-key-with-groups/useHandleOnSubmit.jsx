import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useGetKeyQuery, useDeleteKeyMutation } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { useCallback } from 'react';

export default () => {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload.data?.uuid;
  const { submitForm } = useFormbitContext();

  const { data } = useGetKeyQuery(uuid);
  const name = data?.name;

  const [trigger, args] = useDeleteKeyMutation({ fixedCacheKey: `delete-key-${uuid}` });

  const handleOnSubmit = useCallback(() => {
    if (args.isLoading) {
      return;
    }

    submitForm(async (_, setError) => {
      const { error } = await trigger({
        uuid,
        successMessage: (<SuccessMessage prefix="Credential" strong={name} suffix="deleted" />),
      });

      if (error) {
        setError('silent.backend', getMessageFromQueryError(error));
        return;
      }

      hideModal();
    });
  }, [args.isLoading, hideModal, submitForm, trigger, uuid, name]);

  return { handleOnSubmit, args };
};
