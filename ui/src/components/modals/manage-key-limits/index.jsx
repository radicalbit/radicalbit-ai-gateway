import { formatCount, isLimitComplete } from '@Components/limits/helpers';
import useModals from '@Hooks/use-modals';
import { useGetKeyQuery } from '@State/keys/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Alert, Button, RbitModal, SectionTitle, Spinner,
} from '@radicalbit/radicalbit-design-system';
import AddScreen from './add-screen';
import DeleteScreen from './delete-screen';
import ListScreen from './list-screen';
import { ScreenEnum, getInitialValues, schema } from './schema';
import useHandleOnDelete from './useHandleOnDelete';
import useHandleOnSubmit from './useHandleOnSubmit';

const UNAVAILABLE_MESSAGE = 'Unable to load this credential, please close and retry later';

const MODAL_WIDTH = 760;

const SCREENS = {
  [ScreenEnum.LIST]: ListScreen,
  [ScreenEnum.ADD]: AddScreen,
  [ScreenEnum.DELETE]: DeleteScreen,
};

const SCREEN_ACTIONS = {
  [ScreenEnum.ADD]: AddActions,
  [ScreenEnum.DELETE]: DeleteActions,
};

function ManageKeyLimits() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { isError, isLoading, isSuccess } = useGetKeyQuery(uuid, { skip: !uuid });

  if (isLoading) {
    return (
      <RbitModal onCancel={hideModal} open width={MODAL_WIDTH}>
        <Spinner />
      </RbitModal>
    );
  }

  if (isError) {
    return (
      <RbitModal onCancel={hideModal} open width={MODAL_WIDTH}>
        <Alert title={UNAVAILABLE_MESSAGE} type="error" />
      </RbitModal>
    );
  }

  if (!isSuccess) {
    return false;
  }

  return (
    <FormbitContextProvider initialValues={getInitialValues()} schema={schema}>
      <ManageKeyLimitsInner />
    </FormbitContextProvider>
  );
}

function ManageKeyLimitsInner() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form } = useFormbitContext();
  const screen = form?.__metadata?.screen;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const name = data?.name;

  const Screen = SCREENS[screen] ?? ListScreen;
  const Actions = SCREEN_ACTIONS[screen];
  const subtitle = `Every request authenticated by ${name} counts against these limits, whatever route it calls.`;
  const actions = Actions ? <Actions /> : false;

  return (
    <RbitModal
      actions={actions}
      aria-label="Limits"
      closable
      header={(
        <SectionTitle
          subtitle={subtitle}
          title="Limits"
        />
      )}
      onCancel={hideModal}
      open
      width={MODAL_WIDTH}
    >
      <Screen />
    </RbitModal>
  );
}

function AddActions() {
  const { form, initialize } = useFormbitContext();
  const count = form?.limits?.length ?? 0;

  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  const handleOnCancel = () => {
    initialize(getInitialValues());
  };

  const saveLabel = `Save ${formatCount(count, 'limit')}`;

  const rows = form?.limits ?? [];
  const isIncomplete = !rows.every(isLimitComplete);
  const hint = isIncomplete ? <span className="mr-auto self-center text-xs text-[var(--coo-fg-secondary)]" id="manage-key-limits-hint">Fill in every field of each limit to save</span> : false;
  const hintId = isIncomplete ? 'manage-key-limits-hint' : undefined;

  return (
    <div className="flex gap-2 justify-end">
      {hint}

      <Button onClick={handleOnCancel} type="secondary-light">Cancel</Button>

      <Button aria-describedby={hintId} disabled={isSubmitDisabled} loading={isLoading} onClick={handleOnSubmit} type="primary">{saveLabel}</Button>
    </div>
  );
}

function DeleteActions() {
  const { args: { isLoading }, handleOnCancel, handleOnDelete } = useHandleOnDelete();

  return (
    <div className="flex gap-2 justify-end">
      <Button onClick={handleOnCancel} type="secondary-light">Cancel</Button>

      <Button loading={isLoading} onClick={handleOnDelete} type="error-light">Delete</Button>
    </div>
  );
}

export default ManageKeyLimits;
