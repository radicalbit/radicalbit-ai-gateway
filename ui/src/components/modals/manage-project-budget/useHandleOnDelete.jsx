import { LimitCategoryEnum, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import focusLimitMenu from '@Components/limits/focus-limit-menu';
import { formatLimitValue, formatLimitWindow } from '@Components/limits/helpers';
import SuccessMessage from '@Components/success-message';
import useModals from '@Hooks/use-modals';
import { useDeleteProjectBudgetLimitMutation, useGetProjectBudgetQuery } from '@State/projects/api';
import { FCK_DELETE_PROJECT_BUDGET_LIMIT } from '@State/projects/fixed-cache-key';
import { useFormbitContext } from '@radicalbit/formbit';
import { getInitialValues } from './schema';

export default () => {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form, initialize } = useFormbitContext();
  const limitUuid = form?.__metadata?.limitUuid;

  const { data, refetch } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const name = data?.name;
  const limit = (data?.limits ?? []).find((item) => item.uuid === limitUuid);

  const [trigger, args] = useDeleteProjectBudgetLimitMutation({ fixedCacheKey: `${FCK_DELETE_PROJECT_BUDGET_LIMIT}-${limitUuid}` });

  const label = `${formatLimitValue(LimitCategoryEnum.BUDGET, limit?.value)} / ${formatLimitWindow(limit?.windowSize)} · ${WINDOW_TYPE_LABELS[limit?.algorithm]}`;

  const handleOnDelete = async () => {
    if (args.isLoading) {
      return;
    }

    const { error } = await trigger({
      uuid,
      limitUuid,
      successMessage: <SuccessMessage prefix="Budget" strong={label} suffix={`deleted from ${name}`} />,
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
