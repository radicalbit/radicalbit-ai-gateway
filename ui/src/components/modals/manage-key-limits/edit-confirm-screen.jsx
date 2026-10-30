import Lucide from '@Components/lucide';
import { COUNTER_RESTARTS_NOTE } from '@Components/limits/constants';
import {
  RuleScopeEnum, formatCount, getRulesMadeStale,
} from '@Components/limits/helpers';
import useModals from '@Hooks/use-modals';
import { useGetAlertsQuery } from '@State/alerts/api';
import { useGetKeyQuery } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, FormField, Skeleton } from '@radicalbit/radicalbit-design-system';
import { ArrowLeft } from 'lucide-react';
import useHandleOnReplace from './useHandleOnReplace';

const STALE_RULES_UNAVAILABLE = 'Unable to check alert rules on this limit.';

const FLUSH_BUTTON = '!min-w-0 !px-0';

function EditConfirmScreen() {
  const { errorMessage, handleOnBack, newLabel, oldLabel } = useHandleOnReplace();

  const errorField = errorMessage ? <FormField message={errorMessage} /> : false;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Button className={FLUSH_BUTTON} icon={<Lucide icon={ArrowLeft} />} onClick={handleOnBack} type="text">Back</Button>
      </div>

      <div className="flex flex-col gap-2 focus:outline-none" data-confirm-question tabIndex={-1}>
        <span>
          {'Replace the limit '}

          <strong>{oldLabel}</strong>

          {' with '}

          <strong>{newLabel}</strong>

          ?
        </span>

        <span className="text-[var(--coo-warning)]">{COUNTER_RESTARTS_NOTE}</span>

        <StaleRules />

        {errorField}
      </div>
    </div>
  );
}

function StaleRules() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form } = useFormbitContext();
  const limitUuid = form?.__metadata?.limitUuid;
  const row = form?.limits?.[0];

  const { data: key } = useGetKeyQuery(uuid, { skip: !uuid });
  const limits = key?.limits ?? [];
  const limit = limits.find((item) => item.uuid === limitUuid);

  const { data: rules, isError, isLoading, isSuccess } = useGetAlertsQuery();

  if (isLoading) {
    return <Skeleton.Input active block size="small" />;
  }

  if (isError) {
    return <span className="text-[var(--coo-warning)]">{STALE_RULES_UNAVAILABLE}</span>;
  }

  if (!isSuccess || !limit) {
    return false;
  }

  const count = getRulesMadeStale({
    limit, limits: [...limits, row], rules: rules ?? [], scope: RuleScopeEnum.CREDENTIAL, targetUuid: uuid,
  }).length;

  if (!count) {
    return false;
  }

  const text = `${formatCount(count, 'alert rule')} on the current limit will become stale.`;

  return <span className="text-[var(--coo-warning)]">{text}</span>;
}

export default EditConfirmScreen;
