import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, TextArea } from '@radicalbit/radicalbit-design-system';

function Description() {
  const { error, form, write } = useFormbitContext();
  const description = form?.description;

  const handleOnChange = ({ target: { value } }) => { write('description', value); };

  return (
    <FormField
      label="Description"
      message={error('description')}
    >
      <TextArea
        onChange={handleOnChange}
        rows={3}
        value={description}
      />
    </FormField>
  );
}

export default Description;
