import { LIMIT_CATEGORY_LABELS, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import {
  RuleScopeEnum, formatCount, formatLimitWindow, getRulesMadeStale,
} from '@Components/limits/helpers';
import SuccessMessage from '@Components/success-message';
import useModals from '@Hooks/use-modals';
import { useGetAlertsQuery } from '@State/alerts/api';
import { useDeleteKeyLimitMutation, useGetKeyQuery } from '@State/keys/api';
import { Popconfirm, SectionTitle, Skeleton, TextWithBold } from '@radicalbit/radicalbit-design-system';

const STALE_RULES_UNAVAILABLE = 'Unable to check alert rules on this limit.';

const DESCRIPTION_WIDTH = 'max-w-80';

function DeleteLimit({ limit }) {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const name = data?.name;

  const limitUuid = limit?.uuid;
  const label = `${LIMIT_CATEGORY_LABELS[limit?.category]} ${formatLimitWindow(limit?.windowSize)} · ${WINDOW_TYPE_LABELS[limit?.algorithm]}`;

  const [trigger] = useDeleteKeyLimitMutation({ fixedCacheKey: `delete-key-limit-${limitUuid}` });

  const handleOnDelete = async () => {
    const { error } = await trigger({
      uuid,
      limitUuid,
      successMessage: <SuccessMessage prefix="Limit" strong={label} suffix={`deleted from ${name}`} />,
    });

    if (error) {
      console.error(error);
    }
  };

  const handleOnCancel = (e) => {
    e.stopPropagation();
  };

  return (
    <Popconfirm
      arrow={false}
      cancelButtonProps={{ type: 'secondary-light' }}
      description={(
        <div className={`flex flex-col gap-2 ${DESCRIPTION_WIDTH}`}>
          <TextWithBold bold={label} isQuestion text="Are you sure you want to delete the limit" />

          <StaleRules limit={limit} />
        </div>
      )}
      label={<div className="is-error">Delete</div>}
      okText={<div className="is-error">Delete</div>}
      okType="error-light"
      onCancel={handleOnCancel}
      onConfirm={handleOnDelete}
      title={<SectionTitle size="small" title="Delete limit" titleColor="error" />}
    />
  );
}

function StaleRules({ limit }) {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data: key } = useGetKeyQuery(uuid, { skip: !uuid });
  const limits = key?.limits ?? [];

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
    limit, limits, rules: rules ?? [], scope: RuleScopeEnum.CREDENTIAL, targetUuid: uuid,
  }).length;

  if (!count) {
    return false;
  }

  const text = `${formatCount(count, 'alert rule')} on this limit will become stale.`;

  return <span className="text-[var(--coo-warning)]">{text}</span>;
}

export default DeleteLimit;
