import useModals from '@Hooks/use-modals';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import {
  Button,
  FormField,
  RbitModal, SectionTitle, Spinner,
} from '@radicalbit/radicalbit-design-system';
import Name from './form-fields/name';
import { schema } from './schema';
import useHandleOnSubmit from './useHandleOnSubmit';
import Description from './form-fields/description';

function CreateProject() {
  return (
    <FormbitContextProvider initialValues={{}} schema={schema}>
      <CreateProjectInner />
    </FormbitContextProvider>
  );
}

function CreateProjectInner() {
  const { hideModal } = useModals();
  const { error } = useFormbitContext();

  return (
    <RbitModal
      actions={<Actions />}
      closable
      header={(
        <SectionTitle
          subtitle="Create a new project to organize your resources"
          title="Create project"
        />
      )}
      onCancel={hideModal}
      open
      width={400}
    >
      <Spinner isFormWrapper>
        <Name />

        <Description />

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
      Create project
    </Button>
  );
}

export default CreateProject;
