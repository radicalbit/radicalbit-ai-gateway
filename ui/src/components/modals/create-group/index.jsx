import useModals from '@Hooks/use-modals';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Button,
  FormField,
  RbitModal, SectionTitle, Spinner,
} from '@radicalbit/radicalbit-design-system';
import Name from './name';
import { schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';

function CreateGroup() {
  return (
    <FormbitContextProvider initialValues={{}} schema={schema}>
      <CreateGroupInner />
    </FormbitContextProvider>
  );
}

function CreateGroupInner() {
  const { hideModal } = useModals();
  const { error } = useFormbitContext();

  return (
    <RbitModal
      actions={<Actions />}
      closable
      header={(
        <SectionTitle
          subtitle="Each group can be associated with routes and credentials"
          title="Create group"
          titleColor="primary"
        />
      )}
      onCancel={hideModal}
      open
      width={400}
    >
      <Spinner isFormWrapper>
        <Name />

        {error('silent.backend') && <FormField message={error('silent.backend')} />}
      </Spinner>
    </RbitModal>
  );
}

function Actions() {
  const { handleOnSubmit, args: { isLoading }, isSubmitDisabled } = useHandleOnSubmit();

  return (
    <Button
      disabled={isSubmitDisabled}
      loading={isLoading}
      onClick={handleOnSubmit}
      type="primary"
    >
      New group
    </Button>
  );
}

export default CreateGroup;
