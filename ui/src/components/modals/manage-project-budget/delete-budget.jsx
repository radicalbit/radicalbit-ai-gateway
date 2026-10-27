import { LimitCategoryEnum, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import {
  RuleScopeEnum, formatCount, formatLimitValue, formatLimitWindow, getRulesMadeStale,
} from '@Components/limits/helpers';
import SuccessMessage from '@Components/success-message';
import useModals from '@Hooks/use-modals';
import { useGetAlertsQuery } from '@State/alerts/api';
import { useDeleteProjectBudgetLimitMutation, useGetProjectBudgetQuery } from '@State/projects/api';
import { Popconfirm, SectionTitle, Skeleton, TextWithBold } from '@radicalbit/radicalbit-design-system';

const STALE_RULES_UNAVAILABLE = 'Unable to check alert rules on this budget.';

const DESCRIPTION_WIDTH = 'max-w-80';

const LAST_BUDGET_NOTE = 'Once the project has no budget, routes can declare their own budget_limiting again.';

function DeleteBudget({ limit }) {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const name = data?.name;
  const isLastBudget = (data?.limits ?? []).length === 1;

  const limitUuid = limit?.uuid;
  const label = `${formatLimitValue(LimitCategoryEnum.BUDGET, limit?.value)} / ${formatLimitWindow(limit?.windowSize)} · ${WINDOW_TYPE_LABELS[limit?.algorithm]}`;

  const [trigger] = useDeleteProjectBudgetLimitMutation({ fixedCacheKey: `delete-project-budget-${limitUuid}` });

  const handleOnDelete = async () => {
    const { error } = await trigger({
      uuid,
      limitUuid,
      successMessage: <SuccessMessage prefix="Budget" strong={label} suffix={`deleted from ${name}`} />,
    });

    if (error) {
      console.error(error);
    }
  };

  const handleOnCancel = (e) => {
    e.stopPropagation();
  };

  const lastBudgetNote = isLastBudget ? <span className="text-xs opacity-70">{LAST_BUDGET_NOTE}</span> : false;

  return (
    <Popconfirm
      arrow={false}
      cancelButtonProps={{ type: 'secondary-light' }}
      description={(
        <div className={`flex flex-col gap-1 ${DESCRIPTION_WIDTH}`}>
          <TextWithBold bold={label} isQuestion text="Are you sure you want to delete the budget" />

          {lastBudgetNote}

          <StaleRules limit={limit} />
        </div>
      )}
      label={<div className="is-error">Delete</div>}
      okText={<div className="is-error">Delete</div>}
      okType="error-light"
      onCancel={handleOnCancel}
      onConfirm={handleOnDelete}
      title={<SectionTitle size="small" title="Delete budget" titleColor="error" />}
    />
  );
}

function StaleRules({ limit }) {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data: project } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const limits = project?.limits ?? [];

  const { data: rules, isError, isLoading, isSuccess } = useGetAlertsQuery();

  if (isLoading) {
    return <Skeleton.Input active block size="small" />;
  }

  if (isError) {
    return <span className="text-[var(--coo-warning)]">{STALE_RULES_UNAVAILABLE}</span>;
  }

  if (!isSuccess) {
    return false;
  }

  const count = getRulesMadeStale({
    limit, limits, rules: rules ?? [], scope: RuleScopeEnum.PROJECT, targetUuid: uuid,
  }).length;

  if (!count) {
    return false;
  }

  const text = `${formatCount(count, 'alert rule')} on this budget will become stale.`;

  return <span className="text-[var(--coo-warning)]">{text}</span>;
}

export default DeleteBudget;
