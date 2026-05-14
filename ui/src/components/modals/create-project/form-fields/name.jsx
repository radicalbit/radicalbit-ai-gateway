import useAutoFocus from '@Hooks/use-auto-focus';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Input } from '@radicalbit/radicalbit-design-system';
import { useRef } from 'react';
import useHandleOnSubmit from '../useHandleOnSubmit';

function Name() {
  const ref = useRef();

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
      label="Name"
      message={error('name')}
      required
    >
      <Input
        onChange={handleOnChange}
        onPressEnter={handleOnPressEnter}
        readOnly={isLoading}
        ref={ref}
        value={name}
      />
    </FormField>
  );
}

export default Name;
