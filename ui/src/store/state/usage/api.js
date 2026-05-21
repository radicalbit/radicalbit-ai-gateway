import { API_BASE_URL } from '@Api/config';
import { apiService } from '@Src/store/apis';
import timeFiltersQueryParamFactory from '@State/time-filter-query-params-factory';

export const usageApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getCostsSummaryStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        {
          projectUuid, routes, withSavedTokens, from, to, gte,
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

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/costs/summary/stream?${params.toString()}`;
          const eventSource = new EventSource(url, { withCredentials: true });

          eventSource.onmessage = ({ data }) => {
            const parsed = JSON.parse(data);
            updateCachedData(() => parsed);
          };

          eventSource.onerror = (e) => { console.error(e); };

          await cacheEntryRemoved;
          eventSource.close();
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
          const eventSource = new EventSource(url, { withCredentials: true });

          eventSource.onmessage = ({ data }) => {
            const parsed = JSON.parse(data);
            updateCachedData(() => parsed);
          };

          eventSource.onerror = (e) => { console.error(e); };

          await cacheEntryRemoved;
          eventSource.close();
        } catch (error) {
          console.error(error);
        }
      },
    }),

    getTokensChartStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        { projectUuid, routes, from, to, gte },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const init = {};

          const params = timeFiltersQueryParamFactory({ from, to, gte, init });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/tokens/stream?${params.toString()}`;
          const eventSource = new EventSource(url, { withCredentials: true });

          eventSource.onmessage = ({ data }) => {
            const parsed = JSON.parse(data);
            updateCachedData(() => parsed);
          };

          eventSource.onerror = (e) => { console.error(e); };

          await cacheEntryRemoved;
          eventSource.close();
        } catch (error) {
          console.error(error);
        }
      },
    }),

    getInvocationsChartStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        { projectUuid, routes, from, to, gte },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const init = {};

          const params = timeFiltersQueryParamFactory({ from, to, gte, init });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/invocations/stream?${params.toString()}`;
          const eventSource = new EventSource(url, { withCredentials: true });

          eventSource.onmessage = ({ data }) => {
            const parsed = JSON.parse(data);
            updateCachedData(() => parsed);
          };

          eventSource.onerror = (e) => { console.error(e); };

          await cacheEntryRemoved;
          eventSource.close();
        } catch (error) {
          console.error(error);
        }
      },
    }),

    getCostsChartStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        {
          projectUuid, routes, groupBy, from, to, gte,
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

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/costs/stream?${params.toString()}`;
          const eventSource = new EventSource(url, { withCredentials: true });

          eventSource.onmessage = ({ data }) => {
            const parsed = JSON.parse(data);
            updateCachedData(() => parsed);
          };

          eventSource.onerror = (e) => { console.error(e); };

          await cacheEntryRemoved;
          eventSource.close();
        } catch (error) {
          console.error(error);
        }
      },
    }),

    getCostsByModelStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        {
          projectUuid, modelId, routes, from, to, gte,
        },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = timeFiltersQueryParamFactory({ from, to, gte, init: {} });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/costs/model/${encodeURIComponent(modelId)}/stream?${params.toString()}`;
          const eventSource = new EventSource(url, { withCredentials: true });

          eventSource.onmessage = ({ data }) => {
            const parsed = JSON.parse(data);
            updateCachedData(() => parsed);
          };

          eventSource.onerror = (e) => { console.error(e); };

          await cacheEntryRemoved;
          eventSource.close();
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
          projectUuid, groupUuid, routes, from, to, gte,
        },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = timeFiltersQueryParamFactory({ from, to, gte, init: {} });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/costs/group/${encodeURIComponent(groupUuid)}/stream?${params.toString()}`;
          const eventSource = new EventSource(url, { withCredentials: true });

          eventSource.onmessage = ({ data }) => {
            const parsed = JSON.parse(data);
            updateCachedData(() => parsed);
          };

          eventSource.onerror = (e) => { console.error(e); };

          await cacheEntryRemoved;
          eventSource.close();
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
          projectUuid, keyUuid, routes, from, to, gte,
        },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = timeFiltersQueryParamFactory({ from, to, gte, init: {} });

          if (routes && routes.length > 0) {
            routes.forEach((route) => { params.append('routes', route); });
          }

          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/costs/key/${encodeURIComponent(keyUuid)}/stream?${params.toString()}`;
          const eventSource = new EventSource(url, { withCredentials: true });

          eventSource.onmessage = ({ data }) => {
            const parsed = JSON.parse(data);
            updateCachedData(() => parsed);
          };

          eventSource.onerror = (e) => { console.error(e); };

          await cacheEntryRemoved;
          eventSource.close();
        } catch (error) {
          console.error(error);
        }
      },
    }),

    getCostsModelBreakdown: builder.query({
      query: ({ projectUuid, entityId, timestamp, granularity, routes }) => {
        const params = new URLSearchParams({ timestamp, granularity });

        if (routes && routes.length > 0) {
          routes.forEach((route) => { params.append('routes', route); });
        }

        return { url: `/projects/${projectUuid}/routes/costs/model/${encodeURIComponent(entityId)}/breakdown?${params.toString()}` };
      },
    }),

    getCostsGroupBreakdown: builder.query({
      query: ({ projectUuid, entityId, timestamp, granularity, routes }) => {
        const params = new URLSearchParams({ timestamp, granularity });

        if (routes && routes.length > 0) {
          routes.forEach((route) => { params.append('routes', route); });
        }

        return { url: `/projects/${projectUuid}/routes/costs/group/${encodeURIComponent(entityId)}/breakdown?${params.toString()}` };
      },
    }),

    getCostsKeyBreakdown: builder.query({
      query: ({ projectUuid, entityId, timestamp, granularity, routes }) => {
        const params = new URLSearchParams({ timestamp, granularity });

        if (routes && routes.length > 0) {
          routes.forEach((route) => { params.append('routes', route); });
        }

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
  useGetCostsByModelStreamQuery,
  useGetCostsByGroupStreamQuery,
  useGetCostsByKeyStreamQuery,
  useLazyGetCostsModelBreakdownQuery,
  useLazyGetCostsGroupBreakdownQuery,
  useLazyGetCostsKeyBreakdownQuery,
} = usageApiSlice;
