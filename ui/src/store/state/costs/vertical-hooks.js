import { COSTS_GROUP_BY } from '@Container/pages/costs/list/body';
import { useGetAllCostsQuery, useGetCostsByRouteNameQuery, useGetCostsForChartsByRouteNameQuery, useGetInvocationsForChartsByRouteNameQuery, useGetRequestsForChartsByRouteNameQuery, useGetRequestsWithErrorsForChartsByRouteNameQuery, useGetTokensForChartsByRouteNameQuery } from '@State/costs/api';
import { useSearchParams } from 'react-router-dom';

// ✅ Helper hook: extract ?from=...&to=...
const useQueryRangeParams = () => {
  const [searchParams] = useSearchParams();
  const gte = searchParams.get('gte') || null;
  const from = searchParams.get('from') || null;
  const to = searchParams.get('to') || null;
  const groupBy = searchParams.get('groupBy') || COSTS_GROUP_BY.groups.key;
  const projectUuid = searchParams.get('projectUuid') || null;

  return {
    gte, from, to, groupBy, projectUuid,
  };
};

const useGetAllCostsWithRange = ({ withSavedTokens }, options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();

  return useGetAllCostsQuery({
    projectUuid, gte, from, to, withSavedTokens,
  }, { skip: !projectUuid, ...options });
};

const useGetCostsForChartsByRouteNameWithRange = ({ routeName }, options) => {
  const { gte, from, to, groupBy, projectUuid } = useQueryRangeParams();

  return useGetCostsForChartsByRouteNameQuery({
    projectUuid, routeName, gte, from, to, groupBy,
  }, { skip: !projectUuid, ...options });
};

const useGetCostsByRouteNameWithRange = ({ routeName, withSavedTokens }, options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();

  return useGetCostsByRouteNameQuery({
    projectUuid, routeName, gte, from, to, withSavedTokens,
  }, { skip: !projectUuid, ...options });
};

const useGetTokensForChartsByRouteNameWithRange = ({ routeName }, options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();

  return useGetTokensForChartsByRouteNameQuery({
    projectUuid, routeName, gte, from, to,
  }, { skip: !projectUuid, ...options });
};

const useGetRequestsForChartsByRouteNameWithRange = ({ routeName }, options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();

  return useGetRequestsForChartsByRouteNameQuery({
    projectUuid, routeName, gte, from, to,
  }, { skip: !projectUuid, ...options });
};

const useGetInvocationsForChartsByRouteNameWithRange = ({ routeName, includeModels }, options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();

  return useGetInvocationsForChartsByRouteNameQuery({
    projectUuid, routeName, gte, from, to, includeModels,
  }, { skip: !projectUuid, ...options });
};

const useGetRequestsWithErrorsForChartsByRouteNameWithRange = ({ routeName }, options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();

  return useGetRequestsWithErrorsForChartsByRouteNameQuery({
    projectUuid, routeName, gte, from, to,
  }, { skip: !projectUuid, ...options });
};

export {
  useGetAllCostsWithRange,
  useGetCostsByRouteNameWithRange,
  useGetCostsForChartsByRouteNameWithRange,
  useGetTokensForChartsByRouteNameWithRange,
  useGetRequestsForChartsByRouteNameWithRange,
  useGetInvocationsForChartsByRouteNameWithRange,
  useGetRequestsWithErrorsForChartsByRouteNameWithRange,
};
