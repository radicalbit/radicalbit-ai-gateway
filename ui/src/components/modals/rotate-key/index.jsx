// PROTOTYPE (AG-1041) — throwaway. Rotation modal, ?modalVariant=E|A: E (radio + presets) was chosen,
// A kept as reference; B, C, D were dropped. No API call: Generate shows a fake value.
// ?hoursToExpiry=N simulates the credential's expiry to try the 10-hour cap and the "< 1 hour" case.
import PrototypeSwitcher, { usePrototypeVariant } from '@Components/prototype-switcher';
import {
  formatExpiry, getDefaultGrace, getExpiryInstant, getMockCredential, isNoGraceOnly, validateGrace,
} from '@Container/pages/keys/list/body/prototype-rotation/mock-rotation';
import useModals from '@Hooks/use-modals';
import { useGetKeyQuery } from '@State/keys/api';
import {
  Button, RbitModal, SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import { useState } from 'react';
import VariantA from './prototype-variant-a';
import VariantE from './prototype-variant-e';
import SuccessModal from './success-modal';

const MODAL_VARIANTS = [
  { key: 'E', name: 'Chosen: radio + presets', Component: VariantE },
  { key: 'A', name: 'Radio + fields (reference)', Component: VariantA },
];

function RotateKey() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { expiresOn } = getMockCredential(uuid);
  const expiryInstant = getExpiryInstant(expiresOn);
  const noGraceOnly = isNoGraceOnly(expiryInstant);

  const [grace, setGrace] = useState(noGraceOnly ? { mode: 'none' } : { mode: 'grace', ...getDefaultGrace(expiryInstant) });
  const [rotated, setRotated] = useState(null);

  if (rotated) {
    return <SuccessModal grace={rotated} />;
  }

  return (
    <RotateModal expiresOn={expiresOn} expiryInstant={expiryInstant} grace={grace} noGraceOnly={noGraceOnly} onChange={setGrace} onGenerate={setRotated} />
  );
}

function RotateModal({
  expiresOn, expiryInstant, grace, noGraceOnly, onChange, onGenerate,
}) {
  const { hideModal, modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const name = data?.name;

  const variant = usePrototypeVariant(MODAL_VARIANTS, 'modalVariant');
  const { Component, width = 550 } = MODAL_VARIANTS.find(({ key }) => key === variant);

  const error = grace.mode === 'grace' ? validateGrace(grace, expiryInstant) : null;
  const isGenerateDisabled = !!error;

  const handleOnGenerate = () => {
    onGenerate(grace);
  };

  return (
    <RbitModal
      actions={<Button disabled={isGenerateDisabled} onClick={handleOnGenerate} type="primary">Generate new value</Button>}
      aria-label="Rotate credential"
      closable
      header={(
        <SectionTitle
          subtitle={`A new value replaces the current one for ${name ?? '…'}. It is shown only once.`}
          title="Rotate credential"
        />
      )}
      onCancel={hideModal}
      open
      width={width}
    >
      {/* Three groups, well apart: the expiry, the field, the prototype debug line */}
      <div className="flex flex-col gap-6">
        <div>
          <span className="opacity-70">Credential expires: </span>

          <strong>{formatExpiry(expiresOn)}</strong>
        </div>

        <Component key={variant} error={error} expiryInstant={expiryInstant} grace={grace} noGraceOnly={noGraceOnly} onChange={onChange} />

        <div style={{ fontFamily: 'monospace', fontSize: 12, opacity: 0.6 }}>
          {`PROTOTYPE · would send gracePeriod: ${JSON.stringify(grace.mode === 'none' ? null : `${grace.amount} ${grace.unit}`)}`}
        </div>
      </div>

      <PrototypeSwitcher bottom={72} param="modalVariant" variants={MODAL_VARIANTS} />
    </RbitModal>
  );
}

export default RotateKey;
