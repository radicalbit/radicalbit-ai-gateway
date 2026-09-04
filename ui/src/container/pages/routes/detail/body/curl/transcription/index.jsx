import { FormbitContextProvider } from '@radicalbit/formbit';
import Inner from './01-inner';
import { initialValues, schema } from './schema';

function TranscriptionCurl() {
  return (
    <FormbitContextProvider initialValues={initialValues} schema={schema}>
      <Inner />
    </FormbitContextProvider>
  );
}

export default TranscriptionCurl;
