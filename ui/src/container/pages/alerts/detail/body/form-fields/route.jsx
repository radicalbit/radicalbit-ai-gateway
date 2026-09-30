import { useGetRoutesQuery } from '@State/routes/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Select, Skeleton } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';

function Route() {
  const id = useId();

  const { error, form, write } = useFormbitContext();
  const projectUuid = form?.project;
  const route = form?.route;

  const { data = [], isError, isLoading } = useGetRoutesQuery({ projectUuid }, { skip: !projectUuid });
  const options = data.map(({ routeName }) => ({ label: routeName, value: routeName }));

  const errorMessage = isError ? 'Unable to load routes, please retry later' : undefined;

  const handleOnChange = (value) => {
    write('route', value);
    write('event', undefined);
  };

  if (isLoading) {
    return <Skeleton.Input active block />;
  }

  return (
    <FormField htmlFor={id} label="Route" message={error('route') || errorMessage} required>
      <Select
        disabled={!projectUuid || isError}
        id={id}
        onChange={handleOnChange}
        options={options}
        placeholder="Select a route"
        value={route}
      />
    </FormField>
  );
}

export default Route;
