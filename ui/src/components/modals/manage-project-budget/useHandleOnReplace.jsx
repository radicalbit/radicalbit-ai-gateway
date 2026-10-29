import { LimitCategoryEnum, OLD_BUDGET_LEFT_MESSAGE, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import focusLimitMenu from '@Components/limits/focus-limit-menu';
import focusLimitRow from '@Components/limits/focus-limit-row';
import { formatLimitValue, formatLimitWindow } from '@Components/limits/helpers';
import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useCreateProjectBudgetLimitsMutation, useDeleteProjectBudgetLimitMutation, useGetProjectBudgetQuery } from '@State/projects/api';
import { FCK_REPLACE_PROJECT_BUDGET_CREATE, FCK_REPLACE_PROJECT_BUDGET_DELETE } from '@State/projects/fixed-cache-key';
import { useFormbitContext } from '@radicalbit/formbit';
import { ScreenEnum, getInitialValues } from './schema';

const getLimitLabel = ({ algorithm, value, windowSize } = {}) => `${formatLimitValue(LimitCategoryEnum.BUDGET, value)} / ${formatLimitWindow(windowSize)} · ${WINDOW_TYPE_LABELS[algorithm]}`;

const getErrorMessage = (queryError) => {
  const detail = queryError?.data?.detail;

  if (Array.isArray(detail) && detail.length) {
    return detail[0].msg.replace(/^Value error, /, '');
  }

  return getMessageFromQueryError(queryError);
};

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

  const isLoading = createArgs.isLoading || deleteArgs.isLoading;
  const isOldLimitLeft = createArgs.isSuccess && deleteArgs.isError;
  const isConfirmDisabled = !row || !limit || isLoading || isOldLimitLeft;
  const newLabel = getLimitLabel(row);
  const oldLabel = getLimitLabel(limit);
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
    errorMessage,
    handleOnBack,
    handleOnCancel,
    handleOnConfirm,
    isConfirmDisabled,
    isLoading,
    newLabel,
    oldLabel,
  };
};
