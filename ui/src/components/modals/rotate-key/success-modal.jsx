// PROTOTYPE (AG-1041) — same success modal as creation, plus one line about the previous value.
import Lucide from '@Components/lucide';
import { formatInstant, getGraceEnd } from '@Container/pages/keys/list/body/prototype-rotation/mock-rotation';
import useModals from '@Hooks/use-modals';
import {
  Button, CopyToClipboard, RbitModal, SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import { Copy } from 'lucide-react';

const FAKE_VALUE = 'sk-rb-PROTOTYPE0000000000000000000000000000';

function SuccessModal({ grace }) {
  const { hideModal } = useModals();

  const previousValueLine = grace.mode === 'none'
    ? 'The previous value has stopped working.'
    : `The previous value keeps working until ${formatInstant(getGraceEnd(grace))}.`;

  return (
    <RbitModal
      actions={<Button onClick={hideModal} type="primary">Done</Button>}
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
        <CopyToClipboard link={FAKE_VALUE} modifier="flex gap-2 items-center justify-center" tooltip={{ mouseEnterDelay: 0 }}>
          {FAKE_VALUE}

          <Lucide icon={Copy} />
        </CopyToClipboard>

        <span className="opacity-70">{previousValueLine}</span>
      </div>
    </RbitModal>
  );
}

export default SuccessModal;
