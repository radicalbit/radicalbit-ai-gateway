import Lucide from '@Components/lucide';
import useModals from '@Hooks/use-modals';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Button,
  CopyToClipboard, RbitModal, SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import { Copy } from 'lucide-react';

function SuccessModal() {
  const { hideModal } = useModals();

  const { form } = useFormbitContext();
  const apiKey = form?.__metadata?.apiKey;

  return (
    <RbitModal
      actions={<Actions />}
      header={(
        <SectionTitle
          subtitle="Please note that we do not display your credentials again after you generate them."
          title="Credential"
          titleColor="primary"
        />
      )}
      maskClosable={false}
      onCancel={hideModal}
      open
      width={600}
    >
      <CopyToClipboard link={apiKey} modifier="flex gap-2 items-center justify-center" tooltip={{ mouseEnterDelay: 0 }}>
        {apiKey}

        <Lucide icon={Copy} />
      </CopyToClipboard>
    </RbitModal>
  );
}

function Actions() {
  const { hideModal } = useModals();

  return (
    <Button
      onClick={hideModal}
      type="primary"
    >
      Done
    </Button>
  );
}
export default SuccessModal;
