import { formatCount } from '@Components/limits/helpers';
import useModals from '@Hooks/use-modals';
import { useGetProjectQuery } from '@State/projects/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Alert, Button, RbitModal, SectionTitle, Spinner,
} from '@radicalbit/radicalbit-design-system';
import AddScreen from './add-screen';
import ListScreen from './list-screen';
import { ScreenEnum, getInitialValues, schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';

const UNAVAILABLE_MESSAGE = 'Unable to load this project, please close and retry later';

const MODAL_WIDTH = 760;

function ManageProjectBudget() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;
  const screen = modalPayload?.data?.screen;

  const { isError, isLoading, isSuccess } = useGetProjectQuery(uuid, { skip: !uuid });

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
  const isAddScreen = form?.__metadata?.screen === ScreenEnum.ADD;

  const { data } = useGetProjectQuery(uuid, { skip: !uuid });
  const name = data?.name;

  const body = isAddScreen ? <AddScreen /> : <ListScreen />;
  const subtitle = `An overall spending cap on every route of ${name}, whoever calls it.`;
  const actions = isAddScreen ? <AddActions /> : false;

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
      {body}
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

  return (
    <div className="flex gap-2 justify-end">
      <Button onClick={handleOnCancel} type="secondary-light">Cancel</Button>

      <Button disabled={isSubmitDisabled} loading={isLoading} onClick={handleOnSubmit} type="primary">{saveLabel}</Button>
    </div>
  );
}

export default ManageProjectBudget;
