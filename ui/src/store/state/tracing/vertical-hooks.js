import { tracesPageSize } from '@Src/constants';
import {
  useGetSpanByIdQuery,
  useGetSpanLatenciesQuery,
  useGetTraceByIdQuery,
  useGetTraceLatenciesQuery,
  useGetTracesChartQuery,
  useGetTracesQuery,
} from '@State/tracing/api';
import { useSearchParams } from 'react-router-dom';

const useQueryRangeParams = () => {
  const [searchParams] = useSearchParams();

  const from = searchParams.get('from') || null;
  const to = searchParams.get('to') || null;
  const projectUuid = searchParams.get('projectUuid') || null;

  const routesParam = searchParams.get('routes');
  const routes = routesParam ? routesParam.split(',') : [];

  return {
    from, to, routes, projectUuid,
  };
};

const useGetTracesChartWithRange = (options) => {
  const { from, to, routes, projectUuid } = useQueryRangeParams();

  return useGetTracesChartQuery({
    projectUuid, from, to, routes,
  }, { skip: !projectUuid, ...options });
};

const useGetTraceLatenciesWithRange = (options) => {
  const { from, to, routes, projectUuid } = useQueryRangeParams();

  return useGetTraceLatenciesQuery({
    projectUuid, from, to, routes,
  }, { skip: !projectUuid, ...options });
};

const useGetSpanLatenciesWithRange = ({ includeOthers, grouped }, options) => {
  const { from, to, routes, projectUuid } = useQueryRangeParams();

  return useGetSpanLatenciesQuery({
    projectUuid, from, to, routes, includeOthers, grouped,
  }, { skip: !projectUuid, ...options });
};

const useGetTracesWithRange = (args, options) => {
  const { from, to, routes, projectUuid } = useQueryRangeParams();
  const page = args?.page;

  return useGetTracesQuery({
    projectUuid, from, to, routes, page, limit: tracesPageSize,
  }, { skip: !projectUuid, ...options });
};

const useGetTraceByIdVertical = (traceId, options) => {
  const { projectUuid } = useQueryRangeParams();

  return useGetTraceByIdQuery({ projectUuid, traceId }, { skip: !projectUuid || !traceId, ...options });
};

const useGetSpanByIdVertical = ({ traceId, spanId }, options) => {
  const { projectUuid } = useQueryRangeParams();

  return useGetSpanByIdQuery({ projectUuid, traceId, spanId }, { skip: !projectUuid || !traceId || !spanId, ...options });
};

export {
  useGetSpanByIdVertical,
  useGetSpanLatenciesWithRange,
  useGetTraceByIdVertical,
  useGetTraceLatenciesWithRange,
  useGetTracesChartWithRange,
  useGetTracesWithRange,
};
