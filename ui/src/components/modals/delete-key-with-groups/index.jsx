import useModals from '@Hooks/use-modals';
import { GATEWAY_OWNER } from '@Src/constants';
import { useGetKeyQuery } from '@State/keys/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Alert,
  Button,
  FormField,
  RbitModal, SectionTitle, Skeleton, Spinner,
} from '@radicalbit/radicalbit-design-system';
import { schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';

const DISABLED_CREDENTIALS_TOOLTIP = 'This credential is managed externally and cannot be modified';

function DeleteKeyWithGroups() {
  return (
    <FormbitContextProvider schema={schema}>
      <DeleteKeyWithGroupsOuter />
    </FormbitContextProvider>
  );
}

function DeleteKeyWithGroupsOuter() {
  const { hideModal } = useModals();

  return (
    <RbitModal
      actions={<Actions />}
      closable
      header={(
        <SectionTitle
          align="center"
          title="Delete credential"
          titleColor="error"
        />
      )}
      onCancel={hideModal}
      open
      width={350}
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
  const name = data?.name || [];
  const groupName = data?.group?.name;

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
      <span>

        {'The credential '}

        <strong>{name}</strong>

        {' is associated to '}

        <strong>{groupName}</strong>

        . Do you still want to delete this?
      </span>

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

  const { data, isLoading, isSuccess } = useGetKeyQuery(uuid, { skip: !uuid });
  const owner = data?.owner;

  const { handleOnSubmit, args: { isLoading: isSubmitting } } = useHandleOnSubmit();

  if (isLoading) {
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

  return (
    <>
      <Button onClick={hideModal} type="secondary-light">
        Cancel
      </Button>

      <Button
        loading={isSubmitting}
        onClick={handleOnSubmit}
        type="error-light"
      >
        Delete
      </Button>
    </>
  );
}

export default DeleteKeyWithGroups;
