import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Input } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';

function Name() {
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const name = form?.name;

  const handleOnChange = ({ target: { value } }) => {
    write('name', value);
  };

  return (
    <FormField htmlFor={id} label="Name" message={error('name')} required>
      <Input id={id} onChange={handleOnChange} value={name} />
    </FormField>
  );
}

export default Name;
