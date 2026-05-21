import { useSearchParams } from 'react-router-dom';
import {
  useGetRoutesQuery,
  useGetRouteByNameQuery,
  useGetMetricsByNameQuery,
  useGetMetricsQuery,
  useGetEventsByRouteQuery,
  useGetMostRequestedRouteQuery,
  useGetTopErrorRouteQuery,
  useGetTopCostRouteQuery,
} from './api';

// ✅ Helper hook: extract ?from=...&to=...
const useQueryRangeParams = () => {
  const [searchParams] = useSearchParams();
  const gte = searchParams.get('gte') || null;
  const from = searchParams.get('from') || null;
  const to = searchParams.get('to') || null;
  const projectUuid = searchParams.get('projectUuid') || null;

  return { gte, from, to, projectUuid };
};

// ✅ Each hook now accepts an optional `options` argument
const useGetRoutesWithRange = (options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();
  return useGetRoutesQuery({ projectUuid, gte, from, to }, { skip: !projectUuid, ...options });
};

const useGetRouteByNameWithRange = (name, options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();
  return useGetRouteByNameQuery({
    projectUuid, gte, name, from, to,
  }, { skip: !projectUuid, ...options });
};

const useGetMetricsByNameWithRange = (name, options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();
  return useGetMetricsByNameQuery({
    projectUuid, gte, name, from, to,
  }, { skip: !projectUuid, ...options });
};

const useGetMetricsWithRange = (options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();
  return useGetMetricsQuery({ projectUuid, gte, from, to }, { skip: !projectUuid, ...options });
};

const useGetEventsByRouteWithRange = (name, options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();
  return useGetEventsByRouteQuery({
    projectUuid, gte, name, from, to,
  }, { skip: !projectUuid, ...options });
};

const useGetMostRequestedRouteWithRange = (options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();
  return useGetMostRequestedRouteQuery({ projectUuid, gte, from, to }, { skip: !projectUuid, ...options });
};

const useGetTopErrorRouteWithRange = (options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();
  return useGetTopErrorRouteQuery({ projectUuid, gte, from, to }, { skip: !projectUuid, ...options });
};

const useGetTopCostRouteWithRange = (options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();
  return useGetTopCostRouteQuery({ projectUuid, gte, from, to }, { skip: !projectUuid, ...options });
};

export {
  useGetRoutesWithRange,
  useGetRouteByNameWithRange,
  useGetMetricsByNameWithRange,
  useGetMetricsWithRange,
  useGetEventsByRouteWithRange,
  useGetMostRequestedRouteWithRange,
  useGetTopErrorRouteWithRange,
  useGetTopCostRouteWithRange,
};
