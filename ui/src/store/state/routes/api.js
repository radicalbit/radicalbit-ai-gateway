import { API_BASE_URL } from '@Api/config';
import { API_TAGS, apiService } from '@Src/store/apis';
import timeFiltersQueryParamFactory from '@State/time-filter-query-params-factory';

export const routesApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getRoutes: builder.query({
      providesTags: () => [API_TAGS.ROUTES],
      query: ({ projectUuid, from, to, gte }) => {
        const params = timeFiltersQueryParamFactory({ from, to, gte, init: { include_groups: 'true' } });

        return ({
          url: `/projects/${projectUuid}/routes?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getAssociableGroupsByRoute: builder.query({
      providesTags: () => [API_TAGS.GROUPS],
      query: ({ projectUuid, routeName }) => ({
        url: `/projects/${projectUuid}/routes/${routeName}/associable-groups?include_routes=true&include_keys=true`,
        method: 'get',
      }),
    }),

    getRouteByName: builder.query({
      providesTags: () => [API_TAGS.ROUTES],
      query: ({ projectUuid, name, from, to, gte }) => {
        const params = timeFiltersQueryParamFactory({ from, to, gte, init: { include_groups: 'true' } });

        return {
          url: `/projects/${projectUuid}/routes/${name}?${params.toString()}`,
          method: 'get',
        };
      },
    }),

    getMetricsByName: builder.query({
      providesTags: () => [API_TAGS.ROUTES],
      query: ({ projectUuid, name, from, to, gte }) => {
        const params = timeFiltersQueryParamFactory({ from, to, gte });

        return {
          url: `/projects/${projectUuid}/routes/${name}/metrics?${params.toString()}`,
          method: 'get',
        };
      },
    }),

    getMetrics: builder.query({
      providesTags: () => [API_TAGS.METRICS],
      query: ({ projectUuid, from, to, gte }) => {
        const params = timeFiltersQueryParamFactory({ from, to, gte });

        return ({
          url: `/projects/${projectUuid}/metrics?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    addGroupsToRoute: builder.mutation({
      query: ({ projectUuid, data, routeName }) => ({
        url: `/projects/${projectUuid}/routes/${routeName}/groups`,
        method: 'patch',
        data,
      }),
      invalidatesTags: (result, _, { data, routeName }) => {
        const groups = data?.groups || [];

        if (result) {
          return [
            API_TAGS.GROUPS,
            ...groups.map((groupUUID) => `${API_TAGS.GROUPS}-${groupUUID}`),
            API_TAGS.ROUTES,
            `${API_TAGS.ROUTES}-${routeName}`,
          ];
        }

        return [];
      },
    }),

    getEventsByRoute: builder.query({
      providesTags: () => [API_TAGS.ROUTES],
      query: ({ projectUuid, name, from, to, gte }) => {
        const params = timeFiltersQueryParamFactory({ from, to, gte });

        return ({
          url: `/projects/${projectUuid}/routes/${name}/events?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getPromptsByRoute: builder.query({
      providesTags: () => [API_TAGS.ROUTES],
      query: ({ projectUuid, name }) => ({
        url: `/projects/${projectUuid}/routes/${name}/prompts`,
        method: 'get',
      }),
    }),

    getMostRequestedRoute: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        { projectUuid, from, to, gte },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = (() => (gte ? `_gte=${gte}` : timeFiltersQueryParamFactory({ from, to, gte }).toString()))();
          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/most-requested/stream?${params}`;
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

    getTopErrorRoute: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        { projectUuid, from, to, gte },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = (() => (gte ? `_gte=${gte}` : timeFiltersQueryParamFactory({ from, to, gte }).toString()))();
          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/most-requested-error/stream?${params}`;
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

    getTopCostRoute: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: null }),
      async onCacheEntryAdded(
        { projectUuid, from, to, gte },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = (() => (gte ? `_gte=${gte}` : timeFiltersQueryParamFactory({ from, to, gte }).toString()))();
          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/most-expensive/stream?${params}`;
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
  }),
});

export const {
  useGetRoutesQuery,
  useGetAssociableGroupsByRouteQuery,
  useGetRouteByNameQuery,
  useGetMetricsByNameQuery,
  useGetMetricsQuery,
  useAddGroupsToRouteMutation,
  useGetEventsByRouteQuery,
  useGetPromptsByRouteQuery,
  useGetMostRequestedRouteQuery,
  useGetTopErrorRouteQuery,
  useGetTopCostRouteQuery,
} = routesApiSlice;

export const selectors = {};
