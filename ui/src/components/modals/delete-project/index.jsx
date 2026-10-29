import useModals from '@Hooks/use-modals';
import { useGetProjectQuery } from '@State/projects/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Alert,
  Button,
  FormField,
  RbitModal,
  SectionTitle,
  Skeleton,
  Spinner,
  TextWithBold,
} from '@radicalbit/radicalbit-design-system';
import { schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';

const UNAVAILABLE_MESSAGE = 'Unable to load this project, please close and retry later';

function DeleteProject() {
  return (
    <FormbitContextProvider schema={schema}>
      <DeleteProjectOuter />
    </FormbitContextProvider>
  );
}

function DeleteProjectOuter() {
  const { hideModal } = useModals();

  return (
    <RbitModal
      actions={<Actions />}
      aria-label="Delete project"
      closable
      header={(
        <SectionTitle
          align="center"
          title="Delete project"
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

  const { data, isError, isLoading } = useGetProjectQuery(uuid, { skip: !uuid });
  const name = data?.name;

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return <Alert title={UNAVAILABLE_MESSAGE} type="error" />;
  }

  return (
    <Spinner isFormWrapper>
      <TextWithBold bold={name} isQuestion text="Are you sure you want to delete the project" />

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

  const { isError, isLoading, isSuccess } = useGetProjectQuery(uuid, { skip: !uuid });

  const { handleOnSubmit, args: { isLoading: isSubmitting } } = useHandleOnSubmit();

  if (isLoading) {
    return (
      <>
        <Skeleton.Button active />

        <Skeleton.Button active />
      </>
    );
  }

  if (isError) {
    return (
      <Button onClick={hideModal} type="secondary-light">
        Close
      </Button>
    );
  }

  if (!isSuccess) {
    return false;
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

export default DeleteProject;
