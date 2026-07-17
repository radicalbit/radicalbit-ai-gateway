import { useLazyGetCostsGroupBreakdownQuery, useLazyGetCostsKeyBreakdownQuery, useLazyGetCostsModelBreakdownQuery } from '@State/usage/api';
import { useSearchParams } from 'react-router-dom';
import { DEFAULT_GROUP_BY, GROUP_BY } from '../group-by';

const LAZY_HOOKS_BY_GROUP_BY = {
  [GROUP_BY.groups.key]: useLazyGetCostsGroupBreakdownQuery,
  [GROUP_BY.credentials.key]: useLazyGetCostsKeyBreakdownQuery,
  [GROUP_BY.models.key]: useLazyGetCostsModelBreakdownQuery,
};

const useLazyGetBreakdownByGroupBy = () => {
  const [searchParams] = useSearchParams();
  const groupBy = searchParams.get('groupBy') || DEFAULT_GROUP_BY;

  const useLazyHook = LAZY_HOOKS_BY_GROUP_BY[groupBy];

  return useLazyHook();
};

export default useLazyGetBreakdownByGroupBy;
