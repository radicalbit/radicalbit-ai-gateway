import { formatCount } from '@Components/limits/helpers';
import useModals from '@Hooks/use-modals';
import { useGetKeyQuery } from '@State/keys/api';
import { useKeyLimitSaveWarnings } from '@State/keys/hooks';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Alert, Button, RbitModal, SectionTitle, Skeleton, Spinner,
} from '@radicalbit/radicalbit-design-system';
import { useEffect } from 'react';
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

const SCREENS = {
  [ScreenEnum.LIST]: ListScreen,
  [ScreenEnum.ADD]: AddScreen,
  [ScreenEnum.DELETE]: DeleteScreen,
  [ScreenEnum.EDIT]: EditScreen,
  [ScreenEnum.EDIT_CONFIRM]: EditConfirmScreen,
};

const SCREEN_ACTIONS = {
  [ScreenEnum.LIST]: ListActions,
  [ScreenEnum.ADD]: AddActions,
  [ScreenEnum.DELETE]: DeleteActions,
  [ScreenEnum.EDIT]: EditActions,
  [ScreenEnum.EDIT_CONFIRM]: EditConfirmActions,
};

function ManageKeyLimits() {
  useResetSavedWarningsOnUnmount();

  return (
    <FormbitContextProvider initialValues={getInitialValues()} schema={schema}>
      <ManageKeyLimitsInner />
    </FormbitContextProvider>
  );
}

function ManageKeyLimitsInner() {
  const { hideModal } = useModals();

  return (
    <RbitModal
      actions={<Footer />}
      aria-label="Manage limits"
      closable
      header={<Header />}
      onCancel={hideModal}
      open
      width={760}
    >
      <Body />
    </RbitModal>
  );
}

function Header() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data, isLoading, isSuccess } = useGetKeyQuery(uuid, { skip: !uuid });
  const name = data?.name;

  if (isLoading) {
    return <SectionTitle subtitle={<Skeleton.Input active size="small" />} title="Manage limits" />;
  }

  if (!isSuccess) {
    return <SectionTitle title="Manage limits" />;
  }

  const subtitle = `Every request authenticated by ${name} counts against these limits, whatever route it calls.`;

  return <SectionTitle subtitle={subtitle} title="Manage limits" />;
}

function Body() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form } = useFormbitContext();
  const screen = form?.__metadata?.screen;

  const { isError, isLoading, isSuccess } = useGetKeyQuery(uuid, { skip: !uuid });

  const Screen = SCREENS[screen] ?? ListScreen;

  if (isLoading) {
    return <Spinner />;
  }

  if (isError) {
    return <Alert title="Unable to load this credential, please close and retry later" type="error" />;
  }

  if (!isSuccess) {
    return false;
  }

  return <Screen />;
}

function Footer() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form } = useFormbitContext();
  const screen = form?.__metadata?.screen;

  const { isSuccess } = useGetKeyQuery(uuid, { skip: !uuid });

  const Actions = SCREEN_ACTIONS[screen];

  if (!isSuccess || !Actions) {
    return false;
  }

  return <Actions />;
}

function ListActions() {
  const { hideModal } = useModals();

  return (
    <div className="flex gap-2 justify-end">
      <Button onClick={hideModal} type="primary">Done</Button>
    </div>
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

  return (
    <div className="flex gap-2 justify-end">
      <Button onClick={handleOnCancel} type="secondary-light">Cancel</Button>

      <Button disabled={isSubmitDisabled} loading={isLoading} onClick={handleOnSubmit} type="primary">{saveLabel}</Button>
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
  const { args: { isLoading }, handleOnCancel, handleOnConfirm, isConfirmDisabled } = useHandleOnReplace();

  return (
    <div className="flex gap-2 justify-end">
      <Button onClick={handleOnCancel} type="secondary-light">Cancel</Button>

      <Button disabled={isConfirmDisabled} loading={isLoading} onClick={handleOnConfirm} type="primary">Replace limit</Button>
    </div>
  );
}

function useResetSavedWarningsOnUnmount() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { clearWarnings } = useKeyLimitSaveWarnings(uuid);

  useEffect(() => clearWarnings, [clearWarnings]);
}

export default ManageKeyLimits;
