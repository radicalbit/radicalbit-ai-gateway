import useModals from '@Hooks/use-modals';
import { GATEWAY_OWNER } from '@Src/constants';
import { useGetGroupQuery } from '@State/groups/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Alert,
  Button,
  FormField,
  RbitModal, SectionTitle, Skeleton, Spinner,
} from '@radicalbit/radicalbit-design-system';
import { schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';

const DISABLED_GROUP_TOOLTIP = 'This group is managed externally and cannot be modified';

function DeleteGroupWithAssociatedItems() {
  return (
    <FormbitContextProvider schema={schema}>
      <DeleteGroupWithAssociatedItemsOuter />
    </FormbitContextProvider>
  );
}

function DeleteGroupWithAssociatedItemsOuter() {
  const { hideModal } = useModals();

  return (
    <RbitModal
      actions={<Actions />}
      closable
      header={(
        <SectionTitle
          align="center"
          title="Delete group"
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

  const { data, isLoading } = useGetGroupQuery(uuid, { skip: !uuid });
  const isExternallyManaged = data ? data.owner !== GATEWAY_OWNER : false;
  const name = data?.name || [];
  const routesCount = data?.routes?.length || 0;
  const keysCount = data?.keys?.length || 0;

  const routesLabel = routesCount === 1 ? 'route' : 'routes';
  const credentialLabel = keysCount === 1 ? 'credential' : 'credentials';

  if (isLoading) {
    return <IsLoading />;
  }

  if (isExternallyManaged) {
    return (
      <Alert message={DISABLED_GROUP_TOOLTIP} type="warning" />
    );
  }

  return (
    <Spinner isFormWrapper>
      <span>

        {'The group '}

        <strong>{name}</strong>

        {' has '}

        <strong>{routesCount}</strong>

        {` ${routesLabel} associated and `}

        <strong>{keysCount}</strong>

        {` ${credentialLabel} associated. Do you still want to delete this?`}
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

  const { data, isLoading, isSuccess } = useGetGroupQuery(uuid, { skip: !uuid });
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

export default DeleteGroupWithAssociatedItems;
