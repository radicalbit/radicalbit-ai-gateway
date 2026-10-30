import { OLD_BUDGET_LEFT_MESSAGE } from '@Components/limits/constants';
import focusLimitMenu from '@Components/limits/focus-limit-menu';
import focusLimitRow from '@Components/limits/focus-limit-row';
import SuccessMessage from '@Components/success-message';
import useModals from '@Hooks/use-modals';
import { useCreateProjectBudgetLimitsMutation, useDeleteProjectBudgetLimitMutation, useGetProjectBudgetQuery } from '@State/projects/api';
import { FCK_REPLACE_PROJECT_BUDGET_CREATE, FCK_REPLACE_PROJECT_BUDGET_DELETE } from '@State/projects/fixed-cache-key';
import { useFormbitContext } from '@radicalbit/formbit';
import { getBudgetLabel, getErrorMessage } from './helpers';
import { ScreenEnum, getInitialValues } from './schema';

export default () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form, initialize, write } = useFormbitContext();
  const limitUuid = form?.__metadata?.limitUuid;
  const row = form?.limits?.[0];

  const { data, refetch } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const name = data?.name;
  const limits = data?.limits ?? [];
  const limit = limits.find((item) => item.uuid === limitUuid);

  const [createLimits, createArgs] = useCreateProjectBudgetLimitsMutation({ fixedCacheKey: `${FCK_REPLACE_PROJECT_BUDGET_CREATE}-${limitUuid}` });
  const [deleteLimit, deleteArgs] = useDeleteProjectBudgetLimitMutation({ fixedCacheKey: `${FCK_REPLACE_PROJECT_BUDGET_DELETE}-${limitUuid}` });

  const args = { isLoading: createArgs.isLoading || deleteArgs.isLoading };
  const isOldLimitLeft = createArgs.isSuccess && deleteArgs.isError;
  const isConfirmDisabled = !row || !limit || args.isLoading || isOldLimitLeft;
  const newLabel = getBudgetLabel(row);
  const oldLabel = getBudgetLabel(limit);
  const createErrorMessage = createArgs.isError ? getErrorMessage(createArgs.error) : undefined;
  const errorMessage = isOldLimitLeft ? OLD_BUDGET_LEFT_MESSAGE : createErrorMessage;

  const resetMutations = () => {
    createArgs.reset();
    deleteArgs.reset();
  };

  const handleOnConfirm = async () => {
    if (isConfirmDisabled) {
      return;
    }

    const { algorithm, value, windowSize } = row;

    const { data: created, error: createError } = await createLimits({
      uuid,
      data: { limits: [{ algorithm, value, windowSize }] },
    });

    if (createError) {
      return;
    }

    const { error: deleteError } = await deleteLimit({
      uuid,
      limitUuid,
      successMessage: <SuccessMessage prefix="Budget" strong={newLabel} suffix={`replaces ${oldLabel} on ${name}`} />,
    });

    if (deleteError) {
      return;
    }

    const newLimitUuid = created?.[0]?.uuid;

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
