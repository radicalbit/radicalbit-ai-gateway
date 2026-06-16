import { API_TAGS, apiService } from '@Src/store/apis';
import timeFiltersQueryParamFactory from '@State/time-filter-query-params-factory';

export const costsApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getAllCosts: builder.query({
      providesTags: () => [API_TAGS.USAGE],
      query: ({ projectUuid, from, to, gte, withSavedTokens }) => {
        const init = {};

        if (withSavedTokens) {
          init._with_saved_tokens = 'true';
        }

        const params = timeFiltersQueryParamFactory({ from, to, gte, init });

        return ({
          url: `/projects/${projectUuid}/usage/costs?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getCostsByRouteName: builder.query({
      providesTags: () => [API_TAGS.USAGE],
      query: ({
        projectUuid, routeName, from, to, gte, withSavedTokens,
      }) => {
        const init = {};

        if (withSavedTokens) {
          init._with_saved_tokens = 'true';
        }

        const params = timeFiltersQueryParamFactory({ from, to, gte, init });

        return ({
          url: `/projects/${projectUuid}/routes/${routeName}/costs/summary?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getCostsForChartsByRouteName: builder.query({
      providesTags: () => [API_TAGS.USAGE],
      query: ({
        projectUuid, routeName, from, to, gte, groupBy,
      }) => {
        const init = {};

        const params = timeFiltersQueryParamFactory({ from, to, gte, init, withTimezone: true });

        if (groupBy) {
          params.append('group_by', groupBy);
        }

        return ({
          url: `/projects/${projectUuid}/routes/${routeName}/costs/chart?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getTokensForChartsByRouteName: builder.query({
      providesTags: () => [API_TAGS.USAGE],
      query: ({ projectUuid, routeName, from, to, gte }) => {
        const init = {};

        const params = timeFiltersQueryParamFactory({ from, to, gte, init, withTimezone: true });

        return ({
          url: `/projects/${projectUuid}/routes/${routeName}/tokens/chart?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getRequestsForChartsByRouteName: builder.query({
      providesTags: () => [API_TAGS.USAGE],
      query: ({ projectUuid, routeName, from, to, gte }) => {
        const init = {};

        const params = timeFiltersQueryParamFactory({ from, to, gte, init, withTimezone: true });

        return ({
          url: `/projects/${projectUuid}/routes/${routeName}/requests/chart?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getInvocationsForChartsByRouteName: builder.query({
      providesTags: () => [API_TAGS.USAGE],
      query: ({
        projectUuid, routeName, from, to, gte, includeModels,
      }) => {
        const init = {};

        if (includeModels) {
          init.include_models = 'true';
        }

        const params = timeFiltersQueryParamFactory({ from, to, gte, init, withTimezone: true });

        return ({
          url: `/projects/${projectUuid}/routes/${routeName}/invocations/chart?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getRequestsWithErrorsForChartsByRouteName: builder.query({
      providesTags: () => [API_TAGS.USAGE],
      query: ({ projectUuid, routeName, from, to, gte }) => {
        const init = {
          show_errors: 'true',
        };

        const params = timeFiltersQueryParamFactory({ from, to, gte, init, withTimezone: true });

        return ({
          url: `/projects/${projectUuid}/routes/${routeName}/requests/chart?${params.toString()}`,
          method: 'get',
        });
      },
    }),
  }),
});

export const {
  useGetAllCostsQuery,
  useGetCostsByRouteNameQuery,
  useGetCostsForChartsByRouteNameQuery,
  useGetTokensForChartsByRouteNameQuery,
  useGetRequestsForChartsByRouteNameQuery,
  useGetInvocationsForChartsByRouteNameQuery,
  useGetRequestsWithErrorsForChartsByRouteNameQuery,
} = costsApiSlice;

export const selectors = {};
