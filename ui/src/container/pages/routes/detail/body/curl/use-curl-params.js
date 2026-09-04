import { useGetProjectQuery } from '@State/projects/api';
import { useParams, useSearchParams } from 'react-router-dom';

const useCurlParams = () => {
  const { name } = useParams();

  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  const { data } = useGetProjectQuery(projectUuid, { skip: !projectUuid });
  const projectName = data?.name;

  return { projectName, routeName: name };
};

export default useCurlParams;
