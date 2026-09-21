import { API_BASE_URL } from '@Api/config';
import { API_TAGS, apiService } from '@Src/store/apis';
import eventSourceWithBackoff from '@State/event-source-with-backoff';
import timeFiltersQueryParamFactory from '@State/time-filter-query-params-factory';

const DEFAULT_MOST_REQUESTED_ROUTE_STATE = {
  route: null,
  isSseLoading: true,
  isSseError: false,
  isSseSuccess: false,
  sseErrorMessage: null,
};

const DEFAULT_TOP_ERROR_ROUTE_STATE = {
  route: null,
  isSseLoading: true,
  isSseError: false,
  isSseSuccess: false,
  sseErrorMessage: null,
};

const DEFAULT_TOP_COST_ROUTE_STATE = {
  route: null,
  isSseLoading: true,
  isSseError: false,
  isSseSuccess: false,
  sseErrorMessage: null,
};

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
      queryFn: () => ({ data: DEFAULT_MOST_REQUESTED_ROUTE_STATE }),
      async onCacheEntryAdded(
        { projectUuid, from, to, gte },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = (() => (gte ? `_gte=${gte}` : timeFiltersQueryParamFactory({ from, to, gte }).toString()))();
          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/most-requested/stream?${params}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => {
              updateCachedData(() => ({
                route: parsed,
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
                draft.sseErrorMessage = 'Unable to stream the most requested route';
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

    getTopErrorRoute: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: DEFAULT_TOP_ERROR_ROUTE_STATE }),
      async onCacheEntryAdded(
        { projectUuid, from, to, gte },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = (() => (gte ? `_gte=${gte}` : timeFiltersQueryParamFactory({ from, to, gte }).toString()))();
          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/most-requested-error/stream?${params}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => {
              updateCachedData(() => ({
                route: parsed,
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
                draft.sseErrorMessage = 'Unable to stream the top error route';
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

    getTopCostRoute: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: DEFAULT_TOP_COST_ROUTE_STATE }),
      async onCacheEntryAdded(
        { projectUuid, from, to, gte },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = (() => (gte ? `_gte=${gte}` : timeFiltersQueryParamFactory({ from, to, gte }).toString()))();
          const url = `${API_BASE_URL}/projects/${projectUuid}/routes/most-expensive/stream?${params}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => {
              updateCachedData(() => ({
                route: parsed,
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
                draft.sseErrorMessage = 'Unable to stream the most expensive route';
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
  }),
});

export const {
  useGetRoutesQuery,
  useGetAssociableGroupsByRouteQuery,
  useGetRouteByNameQuery,
  useGetMetricsQuery,
  useAddGroupsToRouteMutation,
  useGetEventsByRouteQuery,
  useGetPromptsByRouteQuery,
  useGetMostRequestedRouteQuery,
  useGetTopErrorRouteQuery,
  useGetTopCostRouteQuery,
} = routesApiSlice;

export const selectors = {};
