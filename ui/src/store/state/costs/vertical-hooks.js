import { useGetInvocationsForChartsByRouteNameQuery, useGetRequestsWithErrorsForChartsByRouteNameQuery, useGetTokensForChartsByRouteNameQuery } from '@State/costs/api';
import { useSearchParams } from 'react-router-dom';

const useQueryRangeParams = () => {
  const [searchParams] = useSearchParams();
  const gte = searchParams.get('gte') || null;
  const from = searchParams.get('from') || null;
  const to = searchParams.get('to') || null;
  const projectUuid = searchParams.get('projectUuid') || null;

  return {
    gte, from, to, projectUuid,
  };
};

const useGetTokensForChartsByRouteNameWithRange = ({ routeName }, options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();

  return useGetTokensForChartsByRouteNameQuery({
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

export { useGetTokensForChartsByRouteNameWithRange, useGetInvocationsForChartsByRouteNameWithRange, useGetRequestsWithErrorsForChartsByRouteNameWithRange };
