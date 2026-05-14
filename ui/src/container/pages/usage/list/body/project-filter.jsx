import { useGetProjectsQuery } from '@State/projects/api';
import { Select, Skeleton } from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';

function ProjectFilter() {
  const [searchParams, setSearchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid') || undefined;

  const { data = [], isError, isLoading } = useGetProjectsQuery();

  const options = data.map((p) => ({ label: p.name, value: p.uuid }));

  const handleOnChange = (value) => {
    setSearchParams((prev) => {
      if (value) {
        prev.set('projectUuid', value);
      } else {
        prev.delete('projectUuid');
      }

      prev.delete('routes');

      return prev;
    });
  };

  if (isLoading) {
    return <Skeleton.Input active block />;
  }

  return (
    <Select
      allowClear
      disabled={isError}
      onChange={handleOnChange}
      options={options}
      placeholder="Please select"
      style={{ width: 400 }}
      value={projectUuid}
    />
  );
}

export default ProjectFilter;
