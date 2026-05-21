import useModals from '@Hooks/use-modals';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Button,
  FormField,
  RbitModal,
  Spinner,
} from '@radicalbit/radicalbit-design-system';
import Project from './form-fields/project';
import Routes from './form-fields/routes';
import Header from './header';
import { schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';

function AddRoutesToGroups() {
  return (
    <FormbitContextProvider initialValues={{ projectUuid: undefined, routes: [] }} schema={schema}>
      <AddRoutesToGroupsInner />
    </FormbitContextProvider>
  );
}

function AddRoutesToGroupsInner() {
  const { hideModal } = useModals();
  const { error } = useFormbitContext();

  return (
    <RbitModal
      actions={<Actions />}
      closable
      header={<Header />}
      onCancel={hideModal}
      open
      width={550}
    >
      <Spinner isFormWrapper>
        <Project />

        <Routes />

        {error('silent.backend') && <FormField message={error('silent.backend')} />}
      </Spinner>
    </RbitModal>
  );
}

function Actions() {
  const { hideModal } = useModals();
  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  return (
    <>
      <Button onClick={hideModal} type="secondary-light">
        Cancel
      </Button>

      <Button
        disabled={isSubmitDisabled}
        loading={isLoading}
        onClick={handleOnSubmit}
        type="primary"
      >
        Save
      </Button>
    </>
  );
}

export default AddRoutesToGroups;
