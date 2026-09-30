import useAutoFocus from '@Hooks/use-auto-focus';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Input } from '@radicalbit/radicalbit-design-system';
import { useId, useRef } from 'react';
import useHandleOnSubmit from '../useHandleOnSubmit';

function NameWithoutIdp() {
  const ref = useRef();
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const name = form?.name;

  const { handleOnSubmit, args: { isLoading } } = useHandleOnSubmit();
  const handleOnChange = ({ target: { value } }) => { write('name', value); };

  useAutoFocus(ref);

  const handleOnPressEnter = () => {
    handleOnSubmit();
  };

  return (
    <FormField
      htmlFor={id}
      label="Name"
      message={error('name')}
      required
    >
      <Input
        id={id}
        onChange={handleOnChange}
        onPressEnter={handleOnPressEnter}
        readOnly={isLoading}
        ref={ref}
        value={name}
      />
    </FormField>
  );
}

export default NameWithoutIdp;
