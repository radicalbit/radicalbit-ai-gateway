import { useGetRoutesQuery } from '@State/routes/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Select, Skeleton } from '@radicalbit/radicalbit-design-system';

function Route() {
  const { error, form, write } = useFormbitContext();
  const projectUuid = form?.project;
  const route = form?.route;

  const { data = [], isLoading } = useGetRoutesQuery({ projectUuid }, { skip: !projectUuid });
  const options = data.map(({ name }) => ({ label: name, value: name }));

  const handleOnChange = (value) => {
    write('route', value);
    write('event', undefined);
  };

  if (isLoading) {
    return <Skeleton.Input active block />;
  }

  return (
    <FormField label="Route" message={error('route')} required>
      <Select
        disabled={!projectUuid}
        onChange={handleOnChange}
        options={options}
        placeholder="Select a route"
        value={route}
      />
    </FormField>
  );
}

export default Route;
