import { API_TAGS, apiService } from '@Src/store/apis';
import timeFiltersQueryParamFactory from '@State/time-filter-query-params-factory';

export const costsApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
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

export const { useGetTokensForChartsByRouteNameQuery, useGetInvocationsForChartsByRouteNameQuery, useGetRequestsWithErrorsForChartsByRouteNameQuery } = costsApiSlice;

export const selectors = {};
