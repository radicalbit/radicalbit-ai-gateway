import useModals from '@Hooks/use-modals';
import { useGetKeyQuery } from '@State/keys/api';
import { FormbitContextProvider, useFormbitContext } from '@radicalbit/formbit';
import { FormField, RbitModal, Spinner } from '@radicalbit/radicalbit-design-system';
import { getInitialValues } from './grace-period';
import RotateModal from './rotate-modal';
import { schema } from './schema';
import SuccessModal from './success-modal';

function RotateKeyModal() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data, isError, isLoading, isSuccess } = useGetKeyQuery(uuid, { skip: !uuid });
  const expiresOn = data?.expiresOn;

  // The initial values depend on the credential's expiry (24 hours, capped to the time left)
  if (isLoading) {
    return (
      <RbitModal onCancel={hideModal} open>
        <Spinner />
      </RbitModal>
    );
  }

  if (isError) {
    return (
      <RbitModal onCancel={hideModal} open>
        <FormField message="Unable to load the credential, please retry later" />
      </RbitModal>
    );
  }

  if (!isSuccess) {
    return false;
  }

  const initialValues = getInitialValues(expiresOn);

  return (
    <FormbitContextProvider initialValues={initialValues} schema={schema}>
      <RotateKeyInner />
    </FormbitContextProvider>
  );
}

function RotateKeyInner() {
  const { form } = useFormbitContext();
  const apiKey = form?.__metadata?.apiKey;

  if (apiKey) {
    return <SuccessModal />;
  }

  return <RotateModal />;
}

export default RotateKeyModal;
