import useAutoFocus from '@Hooks/use-auto-focus';
import useModals from '@Hooks/use-modals';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Button,
  FormField, Input, RbitModal, SectionTitle, Spinner,
} from '@radicalbit/radicalbit-design-system';
import { useRef } from 'react';
import useHandleOnSubmit from './useHandleOnSubmit';

function CreateModal() {
  const { hideModal } = useModals();
  const { error } = useFormbitContext();

  return (
    <RbitModal
      actions={<Actions />}
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
      width={550}
    >
      <Spinner isFormWrapper>
        <Name />

        {error('silent.backend') && <FormField message={error('silent.backend')} />}
      </Spinner>
    </RbitModal>
  );
}

function Name() {
  const ref = useRef();

  const { error, form, write } = useFormbitContext();
  const name = form?.name;

  const { handleOnSubmit, args: { isLoading } } = useHandleOnSubmit();
  const handleOnChange = ({ target: { value } }) => { write('name', value); };

  useAutoFocus(ref);

  return (
    <FormField
      label="Credential name"
      message={error('name')}
      required
    >
      <Input
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
