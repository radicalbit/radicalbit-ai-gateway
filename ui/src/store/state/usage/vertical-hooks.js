import { useGetRoutesQuery } from '@State/routes/api';
import { parseTagsFromTagsKey } from '@State/tags-query-params-factory';
import {
  useGetCostsByGroupStreamQuery,
  useGetCostsByKeyStreamQuery,
  useGetCostsByModelStreamQuery,
  useGetCostsChartStreamQuery,
  useGetCostsSummaryStreamQuery,
  useGetInvocationsChartStreamQuery,
  useGetLimitsStreamQuery,
  useGetTokensChartStreamQuery,
} from '@State/usage/api';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

const useQueryRangeParams = () => {
  const [searchParams] = useSearchParams();
  const gte = searchParams.get('gte') || null;
  const from = searchParams.get('from') || null;
  const to = searchParams.get('to') || null;
  const projectUuid = searchParams.get('projectUuid') || null;

  const tagsKey = searchParams.getAll('tags').join('&');
  const tags = useMemo(() => parseTagsFromTagsKey(tagsKey), [tagsKey]);

  return { gte, from, to, tags, projectUuid };
};

const useGetProjectRoutesWithRange = (options) => {
  const { gte, from, to, projectUuid } = useQueryRangeParams();

  return useGetRoutesQuery({ projectUuid, gte, from, to }, { skip: !projectUuid, ...options });
};

const useGetCostsSummaryStreamWithRange = ({ routes, withSavedTokens }, options) => {
  const { gte, from, to, tags, projectUuid } = useQueryRangeParams();

  return useGetCostsSummaryStreamQuery({
    projectUuid, routes, tags, withSavedTokens, gte, from, to,
  }, options);
};

const useGetTokensChartStreamWithRange = ({ routes }, options) => {
  const { gte, from, to, tags, projectUuid } = useQueryRangeParams();

  return useGetTokensChartStreamQuery({
    projectUuid, routes, tags, gte, from, to,
  }, options);
};

const useGetInvocationsChartStreamWithRange = ({ routes }, options) => {
  const { gte, from, to, tags, projectUuid } = useQueryRangeParams();

  return useGetInvocationsChartStreamQuery({
    projectUuid, routes, tags, gte, from, to,
  }, options);
};

const useGetCostsChartStreamWithRange = ({ routes, groupBy }, options) => {
  const { gte, from, to, tags, projectUuid } = useQueryRangeParams();

  return useGetCostsChartStreamQuery({
    projectUuid, routes, tags, groupBy, gte, from, to,
  }, options);
};

const useGetCostsByModelStreamWithRange = ({ modelId, routes }, options) => {
  const { gte, from, to, tags, projectUuid } = useQueryRangeParams();

  return useGetCostsByModelStreamQuery({
    projectUuid, modelId, routes, tags, gte, from, to,
  }, options);
};

const useGetCostsByGroupStreamWithRange = ({ groupUuid, routes }, options) => {
  const { gte, from, to, tags, projectUuid } = useQueryRangeParams();

  return useGetCostsByGroupStreamQuery({
    projectUuid, groupUuid, routes, tags, gte, from, to,
  }, options);
};

const useGetCostsByKeyStreamWithRange = ({ keyUuid, routes }, options) => {
  const { gte, from, to, tags, projectUuid } = useQueryRangeParams();

  return useGetCostsByKeyStreamQuery({
    projectUuid, keyUuid, routes, tags, gte, from, to,
  }, options);
};

const useGetLimitsStreamWithRange = ({ routes, windowStatuses }, options) => {
  const { projectUuid } = useQueryRangeParams();

  return useGetLimitsStreamQuery({
    projectUuid, routes, windowStatuses,
  }, options);
};

export {
  useGetCostsByGroupStreamWithRange,
  useGetCostsByKeyStreamWithRange,
  useGetCostsByModelStreamWithRange,
  useGetCostsChartStreamWithRange,
  useGetCostsSummaryStreamWithRange,
  useGetInvocationsChartStreamWithRange,
  useGetLimitsStreamWithRange,
  useGetProjectRoutesWithRange,
  useGetTokensChartStreamWithRange,
};
