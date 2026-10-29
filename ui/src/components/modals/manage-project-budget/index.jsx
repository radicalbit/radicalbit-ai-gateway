import { formatCount, isLimitComplete } from '@Components/limits/helpers';
import useModals from '@Hooks/use-modals';
import { useGetProjectBudgetQuery } from '@State/projects/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Alert, Button, RbitModal, SectionTitle, Spinner,
} from '@radicalbit/radicalbit-design-system';
import AddScreen from './add-screen';
import DeleteScreen from './delete-screen';
import EditConfirmScreen from './edit-confirm-screen';
import EditScreen from './edit-screen';
import ListScreen from './list-screen';
import { ScreenEnum, getInitialValues, schema } from './schema';
import useHandleOnDelete from './useHandleOnDelete';
import useHandleOnEdit from './useHandleOnEdit';
import useHandleOnReplace from './useHandleOnReplace';
import useHandleOnSubmit from './useHandleOnSubmit';

const UNAVAILABLE_MESSAGE = 'Unable to load this project, please close and retry later';

const MODAL_WIDTH = 760;

const SCREENS = {
  [ScreenEnum.LIST]: ListScreen,
  [ScreenEnum.ADD]: AddScreen,
  [ScreenEnum.DELETE]: DeleteScreen,
  [ScreenEnum.EDIT]: EditScreen,
  [ScreenEnum.EDIT_CONFIRM]: EditConfirmScreen,
};

const SCREEN_ACTIONS = {
  [ScreenEnum.ADD]: AddActions,
  [ScreenEnum.DELETE]: DeleteActions,
  [ScreenEnum.EDIT]: EditActions,
  [ScreenEnum.EDIT_CONFIRM]: EditConfirmActions,
};

function ManageProjectBudget() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;
  const screen = modalPayload?.data?.screen;

  const { isError, isLoading, isSuccess } = useGetProjectBudgetQuery(uuid, { skip: !uuid });

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
    <FormbitContextProvider initialValues={getInitialValues(screen)} schema={schema}>
      <ManageProjectBudgetInner />
    </FormbitContextProvider>
  );
}

function ManageProjectBudgetInner() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form } = useFormbitContext();
  const screen = form?.__metadata?.screen;

  const { data } = useGetProjectBudgetQuery(uuid, { skip: !uuid });
  const name = data?.name;

  const Screen = SCREENS[screen] ?? ListScreen;
  const Actions = SCREEN_ACTIONS[screen];
  const subtitle = `An overall spending cap on every route of ${name}, whoever calls it.`;
  const actions = Actions ? <Actions /> : false;

  return (
    <RbitModal
      actions={actions}
      aria-label="Budget limits"
      closable
      header={(
        <SectionTitle
          subtitle={subtitle}
          title="Budget limits"
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

  const saveLabel = `Save ${formatCount(count, 'budget')}`;

  const rows = form?.limits ?? [];
  const isIncomplete = !rows.every(isLimitComplete);
  const hint = isIncomplete ? <span className="mr-auto self-center text-xs text-[var(--coo-fg-secondary)]" id="manage-project-budget-hint">Fill in every field of each budget to save</span> : false;
  const hintId = isIncomplete ? 'manage-project-budget-hint' : undefined;

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

function EditActions() {
  const { args: { isLoading }, handleOnCancel, handleOnSave, isSaveDisabled } = useHandleOnEdit();

  return (
    <div className="flex gap-2 justify-end">
      <Button onClick={handleOnCancel} type="secondary-light">Cancel</Button>

      <Button disabled={isSaveDisabled} loading={isLoading} onClick={handleOnSave} type="primary">Save</Button>
    </div>
  );
}

function EditConfirmActions() {
  const { handleOnCancel, handleOnConfirm, isConfirmDisabled, isLoading } = useHandleOnReplace();

  return (
    <div className="flex gap-2 justify-end">
      <Button onClick={handleOnCancel} type="secondary-light">Cancel</Button>

      <Button disabled={isConfirmDisabled} loading={isLoading} onClick={handleOnConfirm} type="primary">Replace budget</Button>
    </div>
  );
}

export default ManageProjectBudget;
