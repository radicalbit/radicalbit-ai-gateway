import Lucide from '@Components/lucide';
import { COUNTER_RESTARTS_NOTE } from '@Components/limits/constants';
import {
  RuleScopeEnum, formatCount, getRulesMadeStale,
} from '@Components/limits/helpers';
import useModals from '@Hooks/use-modals';
import { PathsEnum } from '@Src/constants';
import { useGetAlertsQuery } from '@State/alerts/api';
import { useGetProjectBudgetQuery } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, FormField, Skeleton } from '@radicalbit/radicalbit-design-system';
import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';
import useHandleOnReplace from './useHandleOnReplace';

const STALE_RULES_SUBJECT = 'on the current budget';

const STALE_RULES_UNAVAILABLE = 'Unable to check alert rules on this budget.';

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
          {'Replace the budget '}

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

  const { data: project } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const limits = project?.limits ?? [];
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

  const staleRules = getRulesMadeStale({
    limit, limits: [...limits, row], rules: rules ?? [], scope: RuleScopeEnum.PROJECT, targetUuid: uuid,
  });

  if (!staleRules.length) {
    return false;
  }

  return <StaleRulesText rules={staleRules} />;
}

function StaleRulesText({ rules }) {
  const { hideModal } = useModals();

  if (rules.length === 1) {
    const [rule] = rules;

    return (
      <span className="text-[var(--coo-warning)]">
        {'Alert rule '}

        <Link className="c-anchor light" onClick={hideModal} to={`/${PathsEnum.ALERTS}/${rule.uuid}`}><strong>{rule.name}</strong></Link>

        {` ${STALE_RULES_SUBJECT} will become stale.`}
      </span>
    );
  }

  const title = `${formatCount(rules.length, 'alert rule')} ${STALE_RULES_SUBJECT} will become stale:`;

  return (
    <div className="flex flex-col gap-1 text-[var(--coo-warning)]">
      <span>{title}</span>

      <ul className="m-0 pl-5 list-disc">
        {rules.map((rule) => <li key={rule.uuid}><Link className="c-anchor light" onClick={hideModal} to={`/${PathsEnum.ALERTS}/${rule.uuid}`}>{rule.name}</Link></li>)}
      </ul>
    </div>
  );
}

export default EditConfirmScreen;
