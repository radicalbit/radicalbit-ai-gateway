import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Select } from '@radicalbit/radicalbit-design-system';
import { useState } from 'react';

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const isValidEmail = (email) => EMAIL_REGEX.test(email);

function Recipient() {
  const { error, form, write } = useFormbitContext();
  const recipients = form?.recipients ?? [];
  const [invalidMessage, setInvalidMessage] = useState('');

  const handleOnChange = (nextValues) => {
    const trimmed = nextValues.map((email) => email.trim()).filter(Boolean);
    const valid = trimmed.filter(isValidEmail);
    const invalid = trimmed.filter((email) => !isValidEmail(email));

    write('recipients', valid);
    setInvalidMessage(invalid.length > 0 ? `Invalid email${invalid.length > 1 ? 's' : ''}: ${invalid.join(', ')}` : '');
  };

  const message = invalidMessage || error('recipients');

  return (
    <FormField label="Recipient" message={message} required>
      <Select
        mode="tags"
        onChange={handleOnChange}
        open={false}
        placeholder="Type an email and press Enter"
        suffixIcon={null}
        tokenSeparators={[',', ' ', '\n']}
        value={recipients}
      />
    </FormField>
  );
}

export default Recipient;
