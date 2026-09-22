import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { MCP_DEFAULT_GROUP_BY, MCP_GROUP_BY } from '../group-by';

const useGetNameToId = (chartData) => {
  const [searchParams] = useSearchParams();
  const groupBy = searchParams.get('mcpGroupBy') || MCP_DEFAULT_GROUP_BY;

  return useMemo(() => {
    const d = chartData || [];
    const idMap = {};

    d.forEach(({ name, uuid }) => {
      if (!name) {
        return;
      }

      if (groupBy === MCP_GROUP_BY.services.key) {
        idMap[name] = name;
      } else {
        idMap[name] = uuid;
      }
    });

    return idMap;
  }, [chartData, groupBy]);
};

export default useGetNameToId;
