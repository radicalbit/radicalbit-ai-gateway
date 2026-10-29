import Lucide from '@Components/lucide';
import { LIMIT_CATEGORY_LABELS, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import {
  RuleScopeEnum, formatCount, formatLimitWindow, getRulesMadeStale,
} from '@Components/limits/helpers';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { useGetAlertsQuery } from '@State/alerts/api';
import { useGetKeyQuery } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Button, FormField, Skeleton, TextWithBold,
} from '@radicalbit/radicalbit-design-system';
import { ArrowLeft } from 'lucide-react';
import useHandleOnDelete from './useHandleOnDelete';

const STALE_RULES_UNAVAILABLE = 'Unable to check alert rules on this limit.';

const FLUSH_BUTTON = '!min-w-0 !px-0';

function DeleteScreen() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form } = useFormbitContext();
  const limitUuid = form?.__metadata?.limitUuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const limit = (data?.limits ?? []).find((item) => item.uuid === limitUuid);

  const { args: { error, isError }, handleOnCancel } = useHandleOnDelete();

  const label = `${LIMIT_CATEGORY_LABELS[limit?.category]} ${formatLimitWindow(limit?.windowSize)} · ${WINDOW_TYPE_LABELS[limit?.algorithm]}`;
  const errorField = isError ? <FormField message={getMessageFromQueryError(error)} /> : false;

  if (!limit) {
    return false;
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Button className={FLUSH_BUTTON} icon={<Lucide icon={ArrowLeft} />} onClick={handleOnCancel} type="text">Back</Button>
      </div>

      <div className="flex flex-col gap-2 focus:outline-none" data-delete-question tabIndex={-1}>
        <TextWithBold bold={label} isQuestion text="Are you sure you want to delete the limit" />

        <StaleRules limit={limit} />

        {errorField}
      </div>
    </div>
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

export default DeleteScreen;
