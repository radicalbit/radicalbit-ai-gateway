import { tracesPageSize } from '@Src/constants';
import { parseTagsFromTagsKey } from '@State/tags-query-params-factory';
import {
  useGetSpanByIdQuery,
  useGetSpanLatenciesQuery,
  useGetTraceByIdQuery,
  useGetTraceLatenciesQuery,
  useGetTracesChartQuery,
  useGetTracesQuery,
} from '@State/tracing/api';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

const useQueryRangeParams = () => {
  const [searchParams] = useSearchParams();

  const from = searchParams.get('from') || null;
  const to = searchParams.get('to') || null;
  const projectUuid = searchParams.get('projectUuid') || null;

  const routesParam = searchParams.get('routes');
  const routes = routesParam ? routesParam.split(',') : [];

  const tagsKey = searchParams.getAll('tags').join('&');
  const tags = useMemo(() => parseTagsFromTagsKey(tagsKey), [tagsKey]);

  return {
    from, to, routes, tags, projectUuid,
  };
};

const useGetTracesChartWithRange = (options) => {
  const { from, to, routes, tags, projectUuid } = useQueryRangeParams();

  return useGetTracesChartQuery({
    projectUuid, from, to, routes, tags,
  }, { skip: !projectUuid, ...options });
};

const useGetTraceLatenciesWithRange = (options) => {
  const { from, to, routes, tags, projectUuid } = useQueryRangeParams();

  return useGetTraceLatenciesQuery({
    projectUuid, from, to, routes, tags,
  }, { skip: !projectUuid, ...options });
};

const useGetSpanLatenciesWithRange = ({ includeOthers, grouped }, options) => {
  const { from, to, routes, tags, projectUuid } = useQueryRangeParams();

  return useGetSpanLatenciesQuery({
    projectUuid, from, to, routes, tags, includeOthers, grouped,
  }, { skip: !projectUuid, ...options });
};

const useGetTracesWithRange = (args, options) => {
  const { from, to, routes, tags, projectUuid } = useQueryRangeParams();
  const page = args?.page;

  return useGetTracesQuery({
    projectUuid, from, to, routes, tags, page, limit: tracesPageSize,
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
