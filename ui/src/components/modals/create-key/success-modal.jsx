import useModals from '@Hooks/use-modals';
import { faCopy } from '@fortawesome/free-solid-svg-icons';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Button,
  CopyToClipboard, FontAwesomeIcon, RbitModal, SectionTitle,
} from '@radicalbit/radicalbit-design-system';

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

        <FontAwesomeIcon icon={faCopy} />
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
