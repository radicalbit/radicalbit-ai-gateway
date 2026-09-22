import { useGetProjectsQuery } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Select, Skeleton } from '@radicalbit/radicalbit-design-system';

function Project() {
  const { error, form, write } = useFormbitContext();
  const project = form?.project;

  const { data = [], isError, isLoading } = useGetProjectsQuery();
  const options = data.map(({ name, uuid }) => ({ label: name, value: uuid }));

  const errorMessage = isError ? 'Unable to load projects, please retry later' : undefined;

  const handleOnChange = (value) => {
    write('project', value);
    write('route', undefined);
    write('event', undefined);
  };

  if (isLoading) {
    return <Skeleton.Input active block />;
  }

  return (
    <FormField label="Project" message={error('project') || errorMessage} required>
      <Select
        disabled={isError}
        onChange={handleOnChange}
        options={options}
        placeholder="Select a project"
        value={project}
      />
    </FormField>
  );
}

export default Project;
