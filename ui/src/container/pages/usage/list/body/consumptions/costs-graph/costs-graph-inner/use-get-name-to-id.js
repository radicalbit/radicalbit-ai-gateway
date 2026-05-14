import { useGetCostsChartStreamWithRange } from '@State/usage/vertical-hooks';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

const GROUP_BY_MODELS_KEY = 'models';

const useGetNameToId = () => {
  const [searchParams] = useSearchParams();
  const groupBy = searchParams.get('groupBy') || 'groups';
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const { data } = useGetCostsChartStreamWithRange({ routes, groupBy });

  return useMemo(() => {
    const d = data?.data || [];
    const idMap = {};

    d.forEach(({ name, uuid }) => {
      if (groupBy === GROUP_BY_MODELS_KEY) {
        idMap[name] = name;
      } else {
        idMap[name] = uuid;
      }
    });

    return idMap;
  }, [data?.data, groupBy]);
};

export default useGetNameToId;
