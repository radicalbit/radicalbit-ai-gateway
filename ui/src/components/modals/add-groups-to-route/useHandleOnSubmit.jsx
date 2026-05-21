import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import routesApiSlice from '@State/routes';
import { useFormbitContext } from '@radicalbit/formbit';
import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

const { useAddGroupsToRouteMutation } = routesApiSlice;

export default () => {
  const { hideModal, modalPayload } = useModals();
  const name = modalPayload.data?.name;
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { isFormInvalid, isDirty, submitForm } = useFormbitContext();
  const [trigger, args] = useAddGroupsToRouteMutation({ fixedCacheKey: `add-groups-to-route-${name}` });
  const isSubmitDisabled = !isDirty || isFormInvalid();

  const handleOnSubmit = useCallback(() => {
    if (isSubmitDisabled || args.isLoading) {
      return;
    }

    submitForm(async ({ form: formData }, setError) => {
      const { error: addModelError } = await trigger({
        projectUuid,
        data: formData,
        routeName: name,
        successMessage: (<SuccessMessage prefix="Route" strong={name} suffix="updated" />),
      });

      if (addModelError) {
        setError('silent.backend', getMessageFromQueryError(addModelError));
        return;
      }

      hideModal();
    });
  }, [args.isLoading, hideModal, isSubmitDisabled, name, projectUuid, submitForm, trigger]);

  return { handleOnSubmit, args, isSubmitDisabled };
};
