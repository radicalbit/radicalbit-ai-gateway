import { useLazyGetCostsGroupBreakdownQuery, useLazyGetCostsKeyBreakdownQuery, useLazyGetCostsModelBreakdownQuery } from '@State/usage/api';
import { useSearchParams } from 'react-router-dom';

const LAZY_HOOKS_BY_GROUP_BY = {
  groups: useLazyGetCostsGroupBreakdownQuery,
  keys: useLazyGetCostsKeyBreakdownQuery,
  models: useLazyGetCostsModelBreakdownQuery,
};

const useLazyGetBreakdownByGroupBy = () => {
  const [searchParams] = useSearchParams();
  const groupBy = searchParams.get('groupBy') || 'groups';

  const useLazyHook = LAZY_HOOKS_BY_GROUP_BY[groupBy];

  return useLazyHook();
};

export default useLazyGetBreakdownByGroupBy;
