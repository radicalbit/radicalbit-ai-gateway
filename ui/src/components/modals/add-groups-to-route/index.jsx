import useModals from '@Hooks/use-modals';
import { useGetAssociableGroupsByRouteQuery } from '@State/routes/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Button,
  FormField,
  RbitModal,
  Spinner,
} from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';
import Groups from './form-fields/groups';
import Header from './header';
import { schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';

function AddGroupsToRoute() {
  return (
    <FormbitContextProvider initialValues={{}} schema={schema}>
      <AddGroupsToRouteInner />
    </FormbitContextProvider>
  );
}

function AddGroupsToRouteInner() {
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
        <Groups />

        {error('silent.backend') && <FormField message={error('silent.backend')} />}
      </Spinner>
    </RbitModal>
  );
}

function Actions() {
  const { hideModal, modalPayload } = useModals();
  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  const routeName = modalPayload?.data?.name;
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');
  const { data = [] } = useGetAssociableGroupsByRouteQuery({ projectUuid, routeName }, { skip: !routeName || !projectUuid });

  if (data.length === 0) {
    return false;
  }

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

export default AddGroupsToRoute;
