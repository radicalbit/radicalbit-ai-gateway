import { OLD_LIMIT_LEFT_MESSAGE } from '@Components/limits/constants';
import focusLimitMenu from '@Components/limits/focus-limit-menu';
import focusLimitRow from '@Components/limits/focus-limit-row';
import { getLimitSignature } from '@Components/limits/helpers';
import SuccessMessage from '@Components/success-message';
import useModals from '@Hooks/use-modals';
import { useCreateKeyLimitsMutation, useDeleteKeyLimitMutation, useGetKeyQuery } from '@State/keys/api';
import { FCK_REPLACE_KEY_LIMIT_CREATE, FCK_REPLACE_KEY_LIMIT_DELETE } from '@State/keys/fixed-cache-key';
import { useFormbitContext } from '@radicalbit/formbit';
import { getErrorMessage, getLimitLabel } from './helpers';
import { ScreenEnum, getInitialValues } from './schema';

export default () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form, initialize, write } = useFormbitContext();
  const limitUuid = form?.__metadata?.limitUuid;
  const row = form?.limits?.[0];

  const { data, refetch } = useGetKeyQuery(uuid, { skip: !uuid });
  const name = data?.name;
  const limits = data?.limits ?? [];
  const limit = limits.find((item) => item.uuid === limitUuid);

  const [createLimits, createArgs] = useCreateKeyLimitsMutation({ fixedCacheKey: `${FCK_REPLACE_KEY_LIMIT_CREATE}-${uuid}` });
  const [deleteLimit, deleteArgs] = useDeleteKeyLimitMutation({ fixedCacheKey: `${FCK_REPLACE_KEY_LIMIT_DELETE}-${limitUuid}` });

  const args = { isLoading: createArgs.isLoading || deleteArgs.isLoading };
  const isOldLimitLeft = createArgs.isSuccess && deleteArgs.isError;
  const isConfirmDisabled = !row || !limit || args.isLoading || isOldLimitLeft;
  const newLabel = getLimitLabel(row);
  const oldLabel = getLimitLabel(limit);
  const createErrorMessage = createArgs.isError ? getErrorMessage(createArgs.error) : undefined;
  const errorMessage = isOldLimitLeft ? OLD_LIMIT_LEFT_MESSAGE : createErrorMessage;

  const resetMutations = () => {
    if (createArgs.isError) {
      createArgs.reset();
    }

    deleteArgs.reset();
  };

  const handleOnConfirm = async () => {
    if (isConfirmDisabled) {
      return;
    }

    const { algorithm, category, value, windowSize } = row;

    const { data: createResponse, error: createError } = await createLimits({
      uuid,
      data: {
        limits: [{
          algorithm, category, value, windowSize,
        }],
      },
    });

    if (createError) {
      return;
    }

    const { error: deleteError } = await deleteLimit({
      uuid,
      limitUuid,
      successMessage: <SuccessMessage prefix="Limit" strong={newLabel} suffix={`replaces ${oldLabel} on ${name}`} />,
    });

    if (deleteError) {
      return;
    }

    const newLimitUuid = (createResponse?.key?.limits ?? []).find((item) => getLimitSignature(item) === getLimitSignature(row))?.uuid;

    await refetch();
    resetMutations();
    initialize(getInitialValues());
    focusLimitMenu(newLimitUuid);
  };

  const handleOnBack = () => {
    resetMutations();
    write('__metadata.screen', ScreenEnum.EDIT);
    focusLimitRow(0);
  };

  const handleOnCancel = () => {
    resetMutations();
    initialize(getInitialValues());
    focusLimitMenu(limitUuid);
  };

  return {
    args,
    errorMessage,
    handleOnBack,
    handleOnCancel,
    handleOnConfirm,
    isConfirmDisabled,
    newLabel,
    oldLabel,
  };
};
