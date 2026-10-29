import { DUPLICATE_BUDGET_ERROR, LimitCategoryEnum, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import focusLimitMenu from '@Components/limits/focus-limit-menu';
import {
  asBudgets, formatLimitValue, formatLimitWindow, getNewLimitsErrors, isLimitComplete,
} from '@Components/limits/helpers';
import SuccessMessage from '@Components/success-message';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useGetProjectBudgetQuery, useUpdateProjectBudgetLimitValueMutation } from '@State/projects/api';
import { FCK_UPDATE_PROJECT_BUDGET_LIMIT_VALUE } from '@State/projects/fixed-cache-key';
import { useFormbitContext } from '@radicalbit/formbit';
import { getInitialValues } from './schema';

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

  const { form, initialize, isFormInvalid } = useFormbitContext();
  const limitUuid = form?.__metadata?.limitUuid;
  const row = form?.limits?.[0];

  const { data } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const name = data?.name;
  const limits = data?.limits ?? [];
  const limit = limits.find((item) => item.uuid === limitUuid);

  const [trigger, args] = useUpdateProjectBudgetLimitValueMutation({ fixedCacheKey: `${FCK_UPDATE_PROJECT_BUDGET_LIMIT_VALUE}-${limitUuid}` });

  const otherLimits = asBudgets(limits.filter((item) => item.uuid !== limitUuid));
  const [duplicateError] = getNewLimitsErrors({ duplicateError: DUPLICATE_BUDGET_ERROR, limits: otherLimits, rows: row ? [row] : [] });
  const isWindowChanged = row?.algorithm !== limit?.algorithm || row?.windowSize !== limit?.windowSize;
  const isMaxChanged = row?.value !== limit?.value;
  const isSaveDisabled = !row || !isLimitComplete(row) || isFormInvalid() || !!duplicateError || isWindowChanged || !isMaxChanged || args.isLoading;
  const errorMessage = args.isError ? getErrorMessage(args.error) : undefined;
  const label = `${formatLimitValue(LimitCategoryEnum.BUDGET, limit?.value)} / ${formatLimitWindow(limit?.windowSize)} · ${WINDOW_TYPE_LABELS[limit?.algorithm]}`;

  const handleOnSave = async () => {
    if (isSaveDisabled) {
      return;
    }

    const { error } = await trigger({
      uuid,
      limitUuid,
      data: { value: row.value },
      successMessage: <SuccessMessage prefix="Budget" strong={label} suffix={`updated on ${name}`} />,
    });

    if (error) {
      return;
    }

    initialize(getInitialValues());
    focusLimitMenu(limitUuid);
  };

  const handleOnCancel = () => {
    args.reset();
    initialize(getInitialValues());
    focusLimitMenu(limitUuid);
  };

  return {
    args, duplicateError, errorMessage, handleOnCancel, handleOnSave, isSaveDisabled, isWindowChanged,
  };
};
