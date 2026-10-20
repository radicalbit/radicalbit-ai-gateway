import Lucide from '@Components/lucide';
import useModals from '@Hooks/use-modals';
import { ROTATION_FORMAT } from '@Src/constants';
import { useRotateKeyMutation } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Button,
  CopyToClipboard, RbitModal, SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import dayjs from 'dayjs';
import { Copy } from 'lucide-react';

// Same as the creation success modal, plus when the previous value stops working
function SuccessModal() {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { form } = useFormbitContext();
  const apiKey = form?.__metadata?.apiKey;

  const [, { data }] = useRotateKeyMutation({ fixedCacheKey: `rotate-key-${uuid}` });
  const graceEndsAt = data?.graceEndsAt;

  const previousValueLine = graceEndsAt
    ? `The previous value keeps working until ${dayjs(graceEndsAt).format(ROTATION_FORMAT)}.`
    : 'The previous value has stopped working.';

  return (
    <RbitModal
      actions={<Actions />}
      aria-label="Credential"
      header={(
        <SectionTitle
          subtitle="Please note that we do not display your credentials again after you generate them."
          title="Credential"
        />
      )}
      maskClosable={false}
      onCancel={hideModal}
      open
      width={600}
    >
      <div className="flex flex-col gap-4 items-center">
        <CopyToClipboard link={apiKey} modifier="flex gap-2 items-center justify-center" tooltip={{ mouseEnterDelay: 0 }}>
          {apiKey}

          <Lucide icon={Copy} />
        </CopyToClipboard>

        <span className="opacity-70">{previousValueLine}</span>
      </div>
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
