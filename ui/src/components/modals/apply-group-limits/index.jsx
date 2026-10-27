import { formatCount } from '@Components/limits/helpers';
import useModals from '@Hooks/use-modals';
import { useApplyGroupLimitsMutation, useGetGroupQuery } from '@State/groups/api';
import { useGetKeysQuery } from '@State/keys/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Alert, Button, Divider, FormField, RbitModal, SectionTitle, Spinner,
} from '@radicalbit/radicalbit-design-system';
import { useEffect } from 'react';
import LimitsToApply from './limits-to-apply';
import Preview from './preview';
import { getInitialValues, schema } from './schema';
import useHandleOnSubmit, { getFixedCacheKey } from './useHandleOnSubmit';
import useMembers from './use-members';

const UNAVAILABLE_MESSAGE = 'Unable to load this group, please close and retry later';

const MODAL_WIDTH = 820;

const OutcomeEnum = {
  ADDED: 'added',
  OVERWRITTEN: 'overwritten',
  SKIPPED: 'skipped',
};

function ApplyGroupLimits() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const group = useGetGroupQuery(uuid, { skip: !uuid });
  // Fresh limits, so the preview shows every conflict the apply would meet
  const keys = useGetKeysQuery(undefined, { refetchOnMountOrArgChange: true });

  // The result is kept under a fixed cache key: forget it when the modal closes
  const [, { reset }] = useApplyGroupLimitsMutation({ fixedCacheKey: getFixedCacheKey(uuid) });

  useEffect(() => reset, [reset]);

  if (group.isLoading || keys.isLoading) {
    return (
      <RbitModal onCancel={hideModal} open width={MODAL_WIDTH}>
        <Spinner />
      </RbitModal>
    );
  }

  if (group.isError || keys.isError) {
    return (
      <RbitModal onCancel={hideModal} open width={MODAL_WIDTH}>
        <Alert title={UNAVAILABLE_MESSAGE} type="error" />
      </RbitModal>
    );
  }

  if (!group.isSuccess || !keys.isSuccess) {
    return false;
  }

  return (
    <FormbitContextProvider initialValues={getInitialValues()} schema={schema}>
      <ApplyGroupLimitsInner />
    </FormbitContextProvider>
  );
}

function ApplyGroupLimitsInner() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetGroupQuery(uuid, { skip: !uuid });
  const name = data?.name;

  const [, { data: result }] = useApplyGroupLimitsMutation({ fixedCacheKey: getFixedCacheKey(uuid) });

  const body = result ? <Result result={result} /> : <ApplyForm />;
  const actions = result
    ? <div className="flex justify-end"><Button onClick={hideModal} type="primary">Close</Button></div>
    : <ApplyActions />;

  return (
    <RbitModal
      actions={actions}
      aria-label="Apply limits to credentials"
      closable
      header={<SectionTitle subtitle={name} title="Apply limits to credentials" />}
      onCancel={hideModal}
      open
      width={MODAL_WIDTH}
    >
      {body}
    </RbitModal>
  );
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

// The group owns nothing (ADR 0009): say so before anything is applied
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

  const { members } = useMembers();

  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  const applyLabel = `Apply to ${formatCount(members.length, 'credential')}`;

  return (
    <div className="flex gap-2 justify-end">
      <Button onClick={hideModal} type="secondary-light">Cancel</Button>

      <Button disabled={isSubmitDisabled} loading={isLoading} onClick={handleOnSubmit} type="primary">{applyLabel}</Button>
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

export default ApplyGroupLimits;
