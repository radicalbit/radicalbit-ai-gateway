import { useGetCostsChartStreamWithRange } from '@State/usage/vertical-hooks';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { DEFAULT_GROUP_BY, GROUP_BY } from '../group-by';

const useGetNameToId = () => {
  const [searchParams] = useSearchParams();
  const groupBy = searchParams.get('groupBy') || DEFAULT_GROUP_BY;
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const { data } = useGetCostsChartStreamWithRange({ routes, groupBy });

  return useMemo(() => {
    const d = data?.chart?.data || [];
    const idMap = {};

    d.forEach(({ name, uuid }) => {
      if (groupBy === GROUP_BY.models.key) {
        idMap[name] = name;
      } else {
        idMap[name] = uuid;
      }
    });

    return idMap;
  }, [data?.chart?.data, groupBy]);
};

export default useGetNameToId;
