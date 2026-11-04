import Lucide from '@Components/lucide';
import { RuleScopeEnum, formatCount, getRulesMadeStale } from '@Components/limits/helpers';
import { getMessageFromQueryError } from '@Helpers/errors';
import useModals from '@Hooks/use-modals';
import { PathsEnum } from '@Src/constants';
import { useGetAlertsQuery } from '@State/alerts/api';
import { useGetKeyQuery } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, FormField, Skeleton, TextWithBold } from '@radicalbit/radicalbit-design-system';
import { ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';
import { getLimitLabel } from './helpers';
import useHandleOnDelete from './useHandleOnDelete';

const STALE_RULES_SUBJECT = 'on this limit';

const STALE_RULES_UNAVAILABLE = 'Unable to check alert rules on this limit.';

const FLUSH_BUTTON = '!min-w-0 !px-0';

function DeleteScreen() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form } = useFormbitContext();
  const limitUuid = form?.__metadata?.limitUuid;

  const { args: { error, isError }, handleOnCancel } = useHandleOnDelete();

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const limit = (data?.limits ?? []).find((item) => item.uuid === limitUuid);

  const label = getLimitLabel(limit);
  const errorField = isError ? <FormField message={getMessageFromQueryError(error)} /> : false;

  if (!limit) {
    return false;
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Button className={FLUSH_BUTTON} icon={<Lucide icon={ArrowLeft} />} onClick={handleOnCancel} type="text">Back</Button>
      </div>

      <div className="flex flex-col gap-2 focus:outline-none" data-confirm-question tabIndex={-1}>
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

  const staleRules = getRulesMadeStale({
    limit, limits, rules: rules ?? [], scope: RuleScopeEnum.CREDENTIAL, targetUuid: uuid,
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

export default DeleteScreen;
