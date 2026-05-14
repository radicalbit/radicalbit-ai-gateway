import useModals from '@Hooks/use-modals';
import { GATEWAY_OWNER } from '@Src/constants';
import { useGetAssociableKeysByGroupQuery, useGetGroupQuery } from '@State/groups/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Alert,
  Button,
  FormField,
  RbitModal,
  Skeleton,
  Spinner,
} from '@radicalbit/radicalbit-design-system';
import Keys from './form-fields/keys';
import Header from './header';
import { schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';

const DISABLED_GROUP_TOOLTIP = 'This group is managed externally and cannot be modified';

function AddKeysToGroups() {
  return (
    <FormbitContextProvider initialValues={{}} schema={schema}>
      <AddKeysToGroupsOuter />
    </FormbitContextProvider>
  );
}

function AddKeysToGroupsOuter() {
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

  const { data, isLoading } = useGetGroupQuery(uuid, { skip: !uuid });
  const isExternallyManaged = data ? data.owner !== GATEWAY_OWNER : false;

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
      <Keys />

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

  const { data: groupData, isLoading: isGroupLoading, isSuccess } = useGetGroupQuery(uuid, { skip: !uuid });
  const owner = groupData?.owner;

  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  const { data: associableKeys = [] } = useGetAssociableKeysByGroupQuery({ groupUuid: uuid }, { skip: !uuid });

  if (isGroupLoading) {
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

  if (associableKeys.length === 0) {
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

export default AddKeysToGroups;
