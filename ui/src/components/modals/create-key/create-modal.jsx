import PrototypeSwitcher, { usePrototypeVariant } from '@Components/prototype-switcher';
import useAutoFocus from '@Hooks/use-auto-focus';
import useModals from '@Hooks/use-modals';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Button,
  FormField, Input, RbitModal, SectionTitle, Spinner,
} from '@radicalbit/radicalbit-design-system';
import { useId, useRef, useState } from 'react';
// PROTOTYPE (AG-1037): 4 variants of the expiry field, switchable via ?modalVariant=A|B|C|D
import VariantA from './prototype-expiry/variant-a';
import VariantB from './prototype-expiry/variant-b';
import VariantC from './prototype-expiry/variant-c';
import VariantD from './prototype-expiry/variant-d';
import useHandleOnSubmit from './useHandleOnSubmit';

const MODAL_VARIANTS = [
  { key: 'A', name: 'Radio + picker', Component: VariantA },
  { key: 'B', name: 'Single picker', Component: VariantB },
  { key: 'C', name: 'Duration presets', Component: VariantC },
  { key: 'D', name: 'Always-visible calendar', Component: VariantD, width: 620 },
];

function CreateModal() {
  const { hideModal } = useModals();
  const { error } = useFormbitContext();
  const variant = usePrototypeVariant(MODAL_VARIANTS, 'modalVariant');
  const { width = 550 } = MODAL_VARIANTS.find(({ key }) => key === variant);

  return (
    <RbitModal
      actions={<Actions />}
      aria-label="Create credential"
      closable
      header={(
        <SectionTitle
          subtitle={(
            <>
              Please note that we do not display your credentials again
              <br />
              after you generate them.
            </>
          )}
          title="Create credential"
        />
      )}
      onCancel={hideModal}
      open
      width={width}
    >
      <Spinner isFormWrapper>
        <Name />

        <PrototypeExpiration variant={variant} />

        {error('silent.backend') && <FormField message={error('silent.backend')} />}
      </Spinner>
    </RbitModal>
  );
}

// PROTOTYPE (AG-1037): expiresOn is kept out of the form on purpose — the API doesn't accept it yet (AG-1035)
function PrototypeExpiration({ variant }) {
  const [expiresOn, setExpiresOn] = useState(null);
  const { Component } = MODAL_VARIANTS.find(({ key }) => key === variant);

  return (
    <>
      <Component key={variant} onChange={setExpiresOn} />

      <div style={{ fontFamily: 'monospace', fontSize: 12, opacity: 0.6 }}>
        {`PROTOTYPE · would send expiresOn: ${JSON.stringify(expiresOn)}`}
      </div>

      <PrototypeSwitcher bottom={72} param="modalVariant" variants={MODAL_VARIANTS} />
    </>
  );
}

function Name() {
  const ref = useRef();
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const name = form?.name;

  const { handleOnSubmit, args: { isLoading } } = useHandleOnSubmit();
  const handleOnChange = ({ target: { value } }) => { write('name', value); };

  useAutoFocus(ref);

  return (
    <FormField
      htmlFor={id}
      label="Credential name"
      message={error('name')}
      required
    >
      <Input
        id={id}
        onChange={handleOnChange}
        onPressEnter={handleOnSubmit}
        readOnly={isLoading}
        ref={ref}
        value={name}
      />
    </FormField>
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
      Generate credential
    </Button>
  );
}

export default CreateModal;
