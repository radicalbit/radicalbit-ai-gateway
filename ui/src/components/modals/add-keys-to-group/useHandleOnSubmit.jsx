import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useAddKeysToGroupMutation, useGetGroupQuery } from '@State/groups/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { useCallback } from 'react';

export default () => {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload.data?.uuid;

  const { data } = useGetGroupQuery(uuid);
  const name = data?.name;

  const { form, isFormInvalid, isDirty, submitForm } = useFormbitContext();

  const [trigger, args] = useAddKeysToGroupMutation({ fixedCacheKey: `add-keys-to-groups-${uuid}` });
  const hasNoSelectedKeys = !form?.keys?.length;
  const isSubmitDisabled = !isDirty || isFormInvalid() || hasNoSelectedKeys;

  const handleOnSubmit = useCallback(() => {
    if (isSubmitDisabled || args.isLoading) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const { error: addModelError } = await trigger({
        data: formData,
        uuid,
        successMessage: (<SuccessMessage prefix="Group" strong={name} suffix="updated" />),
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
