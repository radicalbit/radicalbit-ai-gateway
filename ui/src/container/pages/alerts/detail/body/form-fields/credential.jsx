import { AlertScopeEnum, AlertTimeAggregationEnum } from '@Src/constants';
import { useGetKeysQuery } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Select, Skeleton } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';

function Credential() {
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const credential = form?.credential;
  const scope = form?.scope;

  const isCredentialScope = scope === AlertScopeEnum.CREDENTIAL;

  const { data = [], isError, isLoading } = useGetKeysQuery(undefined, { skip: !isCredentialScope });
  const options = data.map(({ name, uuid }) => ({ label: name, value: uuid }));

  const errorMessage = isError ? 'Unable to load credentials, please retry later' : undefined;

  const handleOnChange = (value) => {
    write('credential', value);
    write('event', undefined);
    write('timeAggregation', AlertTimeAggregationEnum.INSTANT);
  };

  if (!isCredentialScope) {
    return false;
  }

  if (isLoading) {
    return <Skeleton.Input active block />;
  }

  return (
    <FormField htmlFor={id} label="Credential" message={error('credential') || errorMessage} required>
      <Select
        disabled={isError}
        id={id}
        onChange={handleOnChange}
        options={options}
        placeholder="Select a credential"
        value={credential}
      />
    </FormField>
  );
}

export default Credential;
