import { API_BASE_URL } from '@Api/config';
import { apiService } from '@Src/store/apis';
import eventSourceWithBackoff from '@State/event-source-with-backoff';
import { appendTagsToParams } from '@State/tags-query-params-factory';
import timeFiltersQueryParamFactory from '@State/time-filter-query-params-factory';

const DEFAULT_MCP_SERVERS_CHART_STATE = {
  chart: null,
  isSseLoading: true,
  isSseError: false,
  isSseSuccess: false,
  sseErrorMessage: null,
};

export const usageApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getCostsSummaryStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        {
          projectUuid, routes, tags, withSavedTokens, from, to, gte,
        },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const init = {};

          if (withSavedTokens) {
            init._with_saved_tokens = 'true';
          }

          const params = timeFiltersQueryParamFactory({ from, to, gte, init });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          appendTagsToParams(params, tags);

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/costs/summary/stream?${params.toString()}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => { updateCachedData(() => parsed); },
          });

          await cacheEntryRemoved;
          subscription.close();
        } catch (error) {
          console.error(error);
        }
      },
    }),

    getLimitsStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        { projectUuid, routes, windowStatuses },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const init = {};
          const params = new URLSearchParams(init);

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          if (windowStatuses && windowStatuses.length > 0) {
            windowStatuses.forEach((status) => { params.append('window_statuses', status); });
          }

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/limits/stream?${params.toString()}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => { updateCachedData(() => parsed); },
          });

          await cacheEntryRemoved;
          subscription.close();
        } catch (error) {
          console.error(error);
        }
      },
    }),

    getTokensChartStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        {
          projectUuid, routes, tags, from, to, gte,
        },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const init = {};

          const params = timeFiltersQueryParamFactory({ from, to, gte, init });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          appendTagsToParams(params, tags);

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/tokens/stream?${params.toString()}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => { updateCachedData(() => parsed); },
          });

          await cacheEntryRemoved;
          subscription.close();
        } catch (error) {
          console.error(error);
        }
      },
    }),

    getInvocationsChartStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        {
          projectUuid, routes, tags, from, to, gte,
        },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const init = {};

          const params = timeFiltersQueryParamFactory({ from, to, gte, init });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          appendTagsToParams(params, tags);

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/invocations/stream?${params.toString()}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => { updateCachedData(() => parsed); },
          });

          await cacheEntryRemoved;
          subscription.close();
        } catch (error) {
          console.error(error);
        }
      },
    }),

    getCostsChartStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: { loading: true, error: false, chart: null } }),
      async onCacheEntryAdded(
        {
          projectUuid, routes, tags, groupBy, from, to, gte,
        },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const init = { group_by: groupBy };

          const params = timeFiltersQueryParamFactory({ from, to, gte, init });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          appendTagsToParams(params, tags);

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/costs/stream?${params.toString()}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => { updateCachedData(() => ({ loading: false, error: false, chart: parsed })); },
            onStreamError: ({ isGivingUp }) => {
              if (isGivingUp) {
                updateCachedData((draft) => { draft.loading = false; draft.error = true; });
              }
            },
          });

          await cacheEntryRemoved;
          subscription.close();
        } catch (error) {
          console.error(error);
          updateCachedData((draft) => { draft.loading = false; draft.error = true; });
        }
      },
    }),

    getMcpServersChartSse: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: DEFAULT_MCP_SERVERS_CHART_STATE }),
      async onCacheEntryAdded(
        {
          projectUuid, routes, tags, groupBy, from, to, gte,
        },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const init = { group_by: groupBy };

          const params = timeFiltersQueryParamFactory({ from, to, gte, init });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          appendTagsToParams(params, tags);

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/mcp/servers/stream?${params.toString()}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => {
              updateCachedData(() => ({
                chart: parsed,
                isSseLoading: false,
                isSseError: false,
                isSseSuccess: true,
                sseErrorMessage: null,
              }));
            },
            onStreamError: () => {
              updateCachedData((draft) => {
                draft.isSseLoading = false;
                draft.isSseError = true;
                draft.isSseSuccess = false;
                draft.sseErrorMessage = 'Unable to stream MCP server invocations';
              });
            },
          });

          await cacheEntryRemoved;
          subscription.close();
        } catch (error) {
          console.error(error);

          updateCachedData((draft) => {
            draft.isSseLoading = false;
            draft.isSseError = true;
            draft.isSseSuccess = false;
            draft.sseErrorMessage = error?.message ?? null;
          });
        }
      },
    }),

    getCostsByModelStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        {
          projectUuid, modelId, routes, tags, from, to, gte,
        },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = timeFiltersQueryParamFactory({ from, to, gte, init: {} });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          appendTagsToParams(params, tags);

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/costs/model/${encodeURIComponent(modelId)}/stream?${params.toString()}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => { updateCachedData(() => parsed); },
          });

          await cacheEntryRemoved;
          subscription.close();
        } catch (error) {
          console.error(error);
        }
      },
    }),

    getCostsByGroupStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        {
          projectUuid, groupUuid, routes, tags, from, to, gte,
        },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = timeFiltersQueryParamFactory({ from, to, gte, init: {} });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          appendTagsToParams(params, tags);

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/costs/group/${encodeURIComponent(groupUuid)}/stream?${params.toString()}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => { updateCachedData(() => parsed); },
          });

          await cacheEntryRemoved;
          subscription.close();
        } catch (error) {
          console.error(error);
        }
      },
    }),

    getCostsByKeyStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        {
          projectUuid, keyUuid, routes, tags, from, to, gte,
        },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = timeFiltersQueryParamFactory({ from, to, gte, init: {} });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          appendTagsToParams(params, tags);

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/costs/key/${encodeURIComponent(keyUuid)}/stream?${params.toString()}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => { updateCachedData(() => parsed); },
          });

          await cacheEntryRemoved;
          subscription.close();
        } catch (error) {
          console.error(error);
        }
      },
    }),

    getMcpKeyUsage: builder.query({
      query: ({
        projectUuid, routes, tags, from, to, gte, page, limit,
      }) => {
        const init = {};

        const params = timeFiltersQueryParamFactory({ from, to, gte, init });

        if (routes && routes.length > 0) {
          routes.forEach((route) => { params.append('routes', route); });
        }

        appendTagsToParams(params, tags);

        if (page !== undefined) {
          params.append('_page', page);
        }

        if (limit !== undefined) {
          params.append('_limit', limit);
        }

        return { url: `/projects/${projectUuid}/usage/mcp/keys?${params.toString()}` };
      },
    }),

    getCostsModelBreakdown: builder.query({
      query: ({
        projectUuid, entityId, timestamp, granularity, routes, tags,
      }) => {
        const params = new URLSearchParams({ timestamp, granularity });

        if (routes && routes.length > 0) {
          routes.forEach((route) => { params.append('routes', route); });
        }

        appendTagsToParams(params, tags);

        return { url: `/projects/${projectUuid}/routes/costs/model/${encodeURIComponent(entityId)}/breakdown?${params.toString()}` };
      },
    }),

    getCostsGroupBreakdown: builder.query({
      query: ({
        projectUuid, entityId, timestamp, granularity, routes, tags,
      }) => {
        const params = new URLSearchParams({ timestamp, granularity });

        if (routes && routes.length > 0) {
          routes.forEach((route) => { params.append('routes', route); });
        }

        appendTagsToParams(params, tags);

        return { url: `/projects/${projectUuid}/routes/costs/group/${encodeURIComponent(entityId)}/breakdown?${params.toString()}` };
      },
    }),

    getCostsKeyBreakdown: builder.query({
      query: ({
        projectUuid, entityId, timestamp, granularity, routes, tags,
      }) => {
        const params = new URLSearchParams({ timestamp, granularity });

        if (routes && routes.length > 0) {
          routes.forEach((route) => { params.append('routes', route); });
        }

        appendTagsToParams(params, tags);

        return { url: `/projects/${projectUuid}/routes/costs/key/${encodeURIComponent(entityId)}/breakdown?${params.toString()}` };
      },
    }),
  }),
});

export const {
  useGetCostsSummaryStreamQuery,
  useGetTokensChartStreamQuery,
  useGetInvocationsChartStreamQuery,
  useGetLimitsStreamQuery,
  useGetCostsChartStreamQuery,
  useGetMcpServersChartSseQuery,
  useGetMcpKeyUsageQuery,
  useGetCostsByModelStreamQuery,
  useGetCostsByGroupStreamQuery,
  useGetCostsByKeyStreamQuery,
  useLazyGetCostsModelBreakdownQuery,
  useLazyGetCostsGroupBreakdownQuery,
  useLazyGetCostsKeyBreakdownQuery,
} = usageApiSlice;
