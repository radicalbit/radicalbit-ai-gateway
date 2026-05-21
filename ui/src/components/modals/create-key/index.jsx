import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import CreateModal from './create-modal';
import { schema } from './schema';
import SuccessModal from './success-modal';

function CreateKeyModal() {
  return (
    <FormbitContextProvider initialValues={{}} schema={schema}>
      <CreateGroupsInner />
    </FormbitContextProvider>
  );
}

function CreateGroupsInner() {
  const { form } = useFormbitContext();
  const apiKey = form?.__metadata?.apiKey;

  if (apiKey) {
    return <SuccessModal />;
  }

  return <CreateModal />;
}

export default CreateKeyModal;
