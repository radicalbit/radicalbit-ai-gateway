import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useAddGroupToKeyMutation, useGetKeyQuery } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { useCallback } from 'react';

export default () => {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload.data?.uuid;

  const { data } = useGetKeyQuery(uuid);
  const name = data?.name;

  const { isFormInvalid, isDirty, submitForm } = useFormbitContext();

  const [trigger, args] = useAddGroupToKeyMutation({ fixedCacheKey: `add-group-to-key-${uuid}` });
  const isSubmitDisabled = !isDirty || isFormInvalid();

  const handleOnSubmit = useCallback(() => {
    if (isSubmitDisabled || args.isLoading) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const { error: addModelError } = await trigger({
        data: formData,
        keyUuid: uuid,
        successMessage: (<SuccessMessage prefix="Credential" strong={name} suffix="updated" />),
      });

      if (addModelError) {
        setError('silent.backend', getMessageFromQueryError(addModelError));
        return;
      }

      hideModal();
    });
  }, [args.isLoading, hideModal, isSubmitDisabled, name, submitForm, trigger, uuid]);

  return { handleOnSubmit, args, isSubmitDisabled };
};
