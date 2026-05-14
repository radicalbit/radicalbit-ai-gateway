import useModals from '@Hooks/use-modals';
import { GATEWAY_OWNER } from '@Src/constants';
import { useGetAssociableGroupsByKeyQuery, useGetKeyQuery } from '@State/keys/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Alert,
  Button,
  FormField,
  RbitModal,
  Skeleton,
  Spinner,
} from '@radicalbit/radicalbit-design-system';
import Group from './form-fields/group';
import Header from './header';
import { schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';

const DISABLED_CREDENTIALS_TOOLTIP = 'This credential is managed externally and cannot be modified';

function AddGroupToKey() {
  return (
    <FormbitContextProvider initialValues={{}} schema={schema}>
      <AddGroupToKeyOuter />
    </FormbitContextProvider>
  );
}

function AddGroupToKeyOuter() {
  const { hideModal } = useModals();

  return (
    <RbitModal
      actions={<Actions />}
      closable
      header={<Header />}
      onCancel={hideModal}
      open
      width={550}
    >
      <Body />
    </RbitModal>
  );
}

function Body() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { error } = useFormbitContext();

  const { data, isLoading } = useGetKeyQuery(uuid, { skip: !uuid });
  const isExternallyManaged = data ? data.owner !== GATEWAY_OWNER : false;

  if (isLoading) {
    return <IsLoading />;
  }

  if (isExternallyManaged) {
    return (
      <Alert message={DISABLED_CREDENTIALS_TOOLTIP} type="warning" />
    );
  }

  return (
    <Spinner isFormWrapper>
      <Group />

      {error('silent.backend') && <FormField message={error('silent.backend')} />}
    </Spinner>
  );
}

function IsLoading() {
  return (
    <Skeleton active block paragraph={{ rows: 1 }} />
  );
}

function Actions() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data: keyData, isLoading: isKeyLoading, isSuccess } = useGetKeyQuery(uuid, { skip: !uuid });
  const owner = keyData?.owner;

  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  const { data: associableGroups = [] } = useGetAssociableGroupsByKeyQuery({ keyUuid: uuid }, { skip: !uuid });

  if (isKeyLoading) {
    return (
      <>
        <Skeleton.Button active />

        <Skeleton.Button active />
      </>
    );
  }

  if (!isSuccess) {
    return null;
  }

  if (owner !== GATEWAY_OWNER) {
    return null;
  }

  if (associableGroups.length === 0) {
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

export default AddGroupToKey;
