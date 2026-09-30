import { useGetProjectsQuery } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Select, Skeleton } from '@radicalbit/radicalbit-design-system';
import { useId } from 'react';

function Project() {
  const id = useId();

  const { form, write } = useFormbitContext();
  const projectUuid = form?.projectUuid;

  const { data = [], isError, isLoading } = useGetProjectsQuery();

  const options = data.map((p) => ({ label: p.name, value: p.uuid }));

  const placeholder = isError ? 'Unable to load projects' : 'Please select';

  const handleOnChange = (value) => {
    write('projectUuid', value);
    write('routes', []);
  };

  if (isLoading) {
    return (
      <FormField label="Project">
        <Skeleton.Input active block />
      </FormField>
    );
  }

  return (
    <FormField htmlFor={id} label="Project">
      <Select
        allowClear
        disabled={isError}
        id={id}
        onChange={handleOnChange}
        optionFilterProp="label"
        options={options}
        placeholder={placeholder}
        showSearch
        value={projectUuid}
      />
    </FormField>
  );
}

export default Project;
