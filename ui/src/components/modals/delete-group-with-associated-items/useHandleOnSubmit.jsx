import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { PathsEnum } from '@Src/constants';
import { useDeleteGroupMutation, useGetGroupQuery } from '@State/groups/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { useCallback } from 'react';
import { useMatch, useNavigate } from 'react-router-dom';

export default () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload.data?.uuid;
  const { submitForm } = useFormbitContext();

  const match = useMatch(`/${PathsEnum.GROUPS}/:uuid`);
  const currentUuid = match?.params.uuid;
  const navigate = useNavigate();

  const { data } = useGetGroupQuery(uuid);
  const name = data?.name;

  const [trigger, args] = useDeleteGroupMutation({ fixedCacheKey: `delete-group-${uuid}` });

  const handleOnSubmit = useCallback(() => {
    if (args.isLoading) {
      return;
    }

    submitForm(async (_, setError) => {
      const { error } = await trigger({
        uuid,
        successMessage: (<SuccessMessage prefix="Group" strong={name} suffix="deleted" />),
      });

      if (error) {
        setError('silent.backend', getMessageFromQueryError(error));
        return;
      }

      if (currentUuid === uuid) {
        navigate(`/${PathsEnum.GROUPS}`, { replace: true });
      }
    });
  }, [args.isLoading, submitForm, trigger, uuid, name, currentUuid, navigate]);

  return { handleOnSubmit, args };
};
