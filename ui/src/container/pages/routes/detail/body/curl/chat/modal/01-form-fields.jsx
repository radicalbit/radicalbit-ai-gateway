import Lucide from '@Components/lucide';
import useAutoFocus from '@Hooks/use-auto-focus';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Input } from '@radicalbit/radicalbit-design-system';
import { KeyRound } from 'lucide-react';
import { useRef } from 'react';

export function ApiKey() {
  const ref = useRef();

  const { error, form, write } = useFormbitContext();
  const apiKey = form?.apiKey;

  const handleOnChange = ({ target: { value } }) => { write('apiKey', value); };

  useAutoFocus(ref);

  return (
    <FormField
      label="Credential"
      message={error('apiKey')}
      required
    >
      <Input
        onChange={handleOnChange}
        placeholder="Paste your credential"
        prefix={<Lucide icon={KeyRound} />}
        ref={ref}
        value={apiKey}
      />
    </FormField>
  );
}
