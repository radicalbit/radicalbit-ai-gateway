import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, TextArea } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';

function Description() {
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const description = form?.description ?? '';

  const handleOnChange = ({ target: { value } }) => {
    write('description', value);
  };

  return (
    <FormField htmlFor={id} label="Description" message={error('description')}>
      <TextArea id={id} onChange={handleOnChange} rows={2} value={description} />
    </FormField>
  );
}

export default Description;
