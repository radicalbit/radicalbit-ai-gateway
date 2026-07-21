import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Input } from '@radicalbit/radicalbit-design-system';

function Name() {
  const { error, form, write } = useFormbitContext();
  const name = form?.name;

  const handleOnChange = ({ target: { value } }) => {
    write('name', value);
  };

  return (
    <FormField label="Name" message={error('name')} required>
      <Input onChange={handleOnChange} value={name} />
    </FormField>
  );
}

export default Name;
