import Lucide from '@Components/lucide';
import useAutoFocus from '@Hooks/use-auto-focus';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Input } from '@radicalbit/radicalbit-design-system';
import { FileAudio, KeyRound } from 'lucide-react';
import { useId, useRef } from 'react';

export function ApiKey() {
  const ref = useRef();
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const apiKey = form?.apiKey;

  const handleOnChange = ({ target: { value } }) => { write('apiKey', value); };

  useAutoFocus(ref);

  return (
    <FormField
      htmlFor={id}
      label="Credential"
      message={error('apiKey')}
      required
    >
      <Input
        id={id}
        onChange={handleOnChange}
        placeholder="Paste your credential"
        prefix={<Lucide icon={KeyRound} />}
        ref={ref}
        value={apiKey}
      />
    </FormField>
  );
}

export function AudioPath() {
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const audioPath = form?.audioPath;

  const handleOnChange = ({ target: { value } }) => { write('audioPath', value); };

  return (
    <FormField
      htmlFor={id}
      label="Audio file path"
      message={error('audioPath')}
      required
    >
      <Input
        id={id}
        onChange={handleOnChange}
        placeholder="/Users/me/audio.mp3"
        prefix={<Lucide icon={FileAudio} />}
        value={audioPath}
      />
    </FormField>
  );
}
