import { useGetProjectsQuery } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Select, Skeleton } from '@radicalbit/radicalbit-design-system';

function Project() {
  const { form, write } = useFormbitContext();
  const projectUuid = form?.projectUuid;

  const { data = [], isError, isLoading } = useGetProjectsQuery();

  const options = data.map((p) => ({ label: p.name, value: p.uuid }));

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
    <FormField label="Project">
      <Select
        allowClear
        disabled={isError}
        onChange={handleOnChange}
        options={options}
        placeholder="Please select"
        value={projectUuid}
      />
    </FormField>
  );
}

export default Project;
