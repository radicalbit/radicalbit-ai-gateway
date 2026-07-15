import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, TextArea } from '@radicalbit/radicalbit-design-system';

// Recipients are stored as an array of strings; the textarea edits them as a
// comma/newline separated list. No domain validation (per product spec).
function Recipient() {
  const { error, form, write } = useFormbitContext();
  const recipients = form?.recipients ?? [];
  const value = recipients.join(', ');

  const handleOnChange = ({ target: { value: nextValue } }) => {
    const parsed = nextValue
      .split(/[,\n]/)
      .map((recipient) => recipient.trim())
      .filter(Boolean);

    write('recipients', parsed);
  };

  return (
    <FormField label="Recipient" message={error('recipients')} required>
      <TextArea
        onChange={handleOnChange}
        placeholder="Email@email.com, Email@email.com"
        rows={3}
        value={value}
      />
    </FormField>
  );
}

export default Recipient;
