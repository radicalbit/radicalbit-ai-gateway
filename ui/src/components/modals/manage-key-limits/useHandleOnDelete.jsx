import focusLimitMenu from '@Components/limits/focus-limit-menu';
import SuccessMessage from '@Components/success-message';
import useModals from '@Hooks/use-modals';
import { useDeleteKeyLimitMutation, useGetKeyQuery } from '@State/keys/api';
import { FCK_DELETE_KEY_LIMIT } from '@State/keys/fixed-cache-key';
import { useFormbitContext } from '@radicalbit/formbit';
import { getLimitLabel } from './helpers';
import { getInitialValues } from './schema';

export default () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form, initialize } = useFormbitContext();
  const limitUuid = form?.__metadata?.limitUuid;

  const { data, refetch } = useGetKeyQuery(uuid, { skip: !uuid });
  const name = data?.name;
  const limit = (data?.limits ?? []).find((item) => item.uuid === limitUuid);

  const [trigger, args] = useDeleteKeyLimitMutation({ fixedCacheKey: `${FCK_DELETE_KEY_LIMIT}-${limitUuid}` });

  const label = getLimitLabel(limit);

  const handleOnDelete = async () => {
    if (args.isLoading) {
      return;
    }

    const { error } = await trigger({
      uuid,
      limitUuid,
      successMessage: <SuccessMessage prefix="Limit" strong={label} suffix={`deleted from ${name}`} />,
    });

    if (error) {
      return;
    }

    await refetch();
    initialize(getInitialValues());
    focusLimitMenu(limitUuid);
  };

  const handleOnCancel = () => {
    args.reset();
    initialize(getInitialValues());
    focusLimitMenu(limitUuid);
  };

  return { args, handleOnCancel, handleOnDelete };
};
