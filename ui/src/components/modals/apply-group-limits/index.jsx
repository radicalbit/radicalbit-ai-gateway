import { formatCount, isLimitComplete } from '@Components/limits/helpers';
import useModals from '@Hooks/use-modals';
import { useApplyGroupLimitsMutation, useGetGroupQuery } from '@State/groups/api';
import { FCK_APPLY_GROUP_LIMITS } from '@State/groups/fixed-cache-key';
import { useGetKeysQuery } from '@State/keys/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Alert, Button, Divider, FormField, RbitModal, SectionTitle, Skeleton, Spinner,
} from '@radicalbit/radicalbit-design-system';
import { useEffect } from 'react';
import LimitsToApply from './limits-to-apply';
import Preview from './preview';
import { getInitialValues, schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';
import useMembers from './use-members';
import useTouchedCount from './use-touched-count';

const UNAVAILABLE_MESSAGE = 'Unable to load this group, please close and retry later';

const MODAL_WIDTH = 820;

const OutcomeEnum = {
  ADDED: 'added',
  OVERWRITTEN: 'overwritten',
  SKIPPED: 'skipped',
};

function ApplyGroupLimits() {
  useResetApplyOnUnmount();

  return (
    <FormbitContextProvider initialValues={getInitialValues()} schema={schema}>
      <ApplyGroupLimitsInner />
    </FormbitContextProvider>
  );
}

function ApplyGroupLimitsInner() {
  const { hideModal } = useModals();

  return (
    <RbitModal
      actions={<Footer />}
      aria-label="Apply limits to credentials"
      closable
      header={<Header />}
      onCancel={hideModal}
      open
      width={MODAL_WIDTH}
    >
      <Body />
    </RbitModal>
  );
}

function Header() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data, isLoading, isSuccess } = useGetGroupQuery(uuid, { skip: !uuid });
  const name = data?.name;

  if (isLoading) {
    return <SectionTitle subtitle={<Skeleton.Input active size="small" />} title="Apply limits to credentials" />;
  }

  if (!isSuccess) {
    return <SectionTitle title="Apply limits to credentials" />;
  }

  return <SectionTitle subtitle={name} title="Apply limits to credentials" />;
}

function Body() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const group = useGetGroupQuery(uuid, { refetchOnMountOrArgChange: true, skip: !uuid });

  const keys = useGetKeysQuery(undefined, { refetchOnMountOrArgChange: true });

  const [, { data: result }] = useApplyGroupLimitsMutation({ fixedCacheKey: `${FCK_APPLY_GROUP_LIMITS}-${uuid}` });

  if (group.isLoading || keys.isLoading) {
    return <Spinner />;
  }

  if (group.isError || keys.isError) {
    return <Alert title={UNAVAILABLE_MESSAGE} type="error" />;
  }

  if (!group.isSuccess || !keys.isSuccess) {
    return false;
  }

  if (result) {
    return <Result result={result} />;
  }

  return <ApplyForm />;
}

function Footer() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const group = useGetGroupQuery(uuid, { skip: !uuid });

  const keys = useGetKeysQuery(undefined);

  const [, { data: result }] = useApplyGroupLimitsMutation({ fixedCacheKey: `${FCK_APPLY_GROUP_LIMITS}-${uuid}` });

  if (!group.isSuccess || !keys.isSuccess) {
    return false;
  }

  if (result) {
    return <div className="flex justify-end"><Button onClick={hideModal} type="primary">Close</Button></div>;
  }

  return <ApplyActions />;
}

function ApplyForm() {
  const { error } = useFormbitContext();

  const { members } = useMembers();

  const backendError = error('silent.backend');
  const backendErrorField = backendError ? <FormField message={backendError} /> : false;

  return (
    <div className="flex flex-col gap-6">
      <CopyExplanation count={members.length} />

      <LimitsToApply />

      <Divider className="!m-0" />

      <Preview />

      {backendErrorField}
    </div>
  );
}

function CopyExplanation({ count }) {
  const description = `These limits are copied onto the ${formatCount(count, 'credential')} in this group right now, each with its own counter. Credentials added to the group later won't receive them, and removing a credential from the group keeps its limits. Change or delete them from each credential.`;

  return (
    <Alert
      description={description}
      showIcon
      title="Limits are applied to each credential, not to the group"
      type="info"
    />
  );
}

function ApplyActions() {
  const { hideModal } = useModals();

  const { form } = useFormbitContext();
  const rows = form?.limits ?? [];

  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  const touchedCount = useTouchedCount();

  const applyLabel = `Apply to ${formatCount(touchedCount, 'credential')}`;
  const isIncomplete = !rows.every(isLimitComplete);
  const hint = isIncomplete ? <span className="mr-auto self-center text-xs text-[var(--coo-fg-secondary)]" id="apply-group-limits-hint">Fill in every field of each limit to apply</span> : false;
  const hintId = isIncomplete ? 'apply-group-limits-hint' : undefined;

  return (
    <div className="flex gap-2 justify-end">
      {hint}

      <Button onClick={hideModal} type="secondary-light">Cancel</Button>

      <Button aria-describedby={hintId} disabled={isSubmitDisabled} loading={isLoading} onClick={handleOnSubmit} type="primary">{applyLabel}</Button>
    </div>
  );
}

function Result({ result }) {
  const outcomes = (result?.members ?? []).flatMap(({ limits }) => limits.map(({ outcome }) => outcome));
  const countOf = (outcome) => outcomes.filter((item) => item === outcome).length;

  const summary = `${formatCount(countOf(OutcomeEnum.ADDED), 'limit')} added, ${countOf(OutcomeEnum.OVERWRITTEN)} overwritten, ${countOf(OutcomeEnum.SKIPPED)} skipped.`;

  return (
    <div className="flex flex-col gap-2">
      <strong>Limits applied</strong>

      <span>{summary}</span>

      <span className="text-xs opacity-70">From now on they belong to each credential: change or delete them from Credentials.</span>
    </div>
  );
}

function useResetApplyOnUnmount() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const [, { reset }] = useApplyGroupLimitsMutation({ fixedCacheKey: `${FCK_APPLY_GROUP_LIMITS}-${uuid}` });

  useEffect(() => reset, [reset]);
}

export default ApplyGroupLimits;
