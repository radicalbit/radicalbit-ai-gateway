import { useGetProjectsQuery } from '@State/projects/api';
import { useFormbitContext } from '@radicalbit/formbit';
import { FormField, Select, Skeleton } from '@radicalbit/radicalbit-design-system';

function Project() {
  const { error, form, write } = useFormbitContext();
  const project = form?.project;

  const { data = [], isLoading } = useGetProjectsQuery();
  const options = data.map(({ name, uuid }) => ({ label: name, value: uuid }));

  const handleOnChange = (value) => {
    write('project', value);
    // Route and event depend on the project: reset them when it changes.
    write('route', undefined);
    write('event', undefined);
  };

  if (isLoading) {
    return <Skeleton.Input active block />;
  }

  return (
    <FormField label="Project" message={error('project')} required>
      <Select
        onChange={handleOnChange}
        options={options}
        placeholder="Select a project"
        value={project}
      />
    </FormField>
  );
}

export default Project;
