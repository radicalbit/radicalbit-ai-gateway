import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import { useGetProjectsQuery, useVerifyProjectQuery } from '@State/projects/api';
import { Select, Skeleton } from '@radicalbit/radicalbit-design-system';
import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

function ProjectFilter() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid') || undefined;

  const { data = [], isError, isLoading } = useGetProjectsQuery();

  const { error: verifyError } = useVerifyProjectQuery(projectUuid, { skip: !projectUuid });
  const isStaleProject = verifyError?.status === 404;

  const options = data.map((p) => ({ label: p.name, value: p.uuid }));

  useEffect(() => {
    if (isStaleProject) {
      const next = new URLSearchParams(searchParams);
      next.delete('projectUuid');
      next.delete(SEARCH_PARAMS.routes);
      navigate(`/${PathsEnum.ROUTES}?${next.toString()}`, { replace: true });
    }
  }, [isStaleProject, navigate, searchParams]);

  const handleOnChange = (value) => {
    const next = new URLSearchParams(searchParams);

    if (value) {
      next.set('projectUuid', value);
    } else {
      next.delete('projectUuid');
    }

    next.delete(SEARCH_PARAMS.routes);

    navigate(`/${PathsEnum.ROUTES}?${next.toString()}`, { replace: true });
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
