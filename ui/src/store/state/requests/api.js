import { API_TAGS, apiService } from '@Src/store/apis';
import { appendTagsToParams } from '@State/tags-query-params-factory';
import timeFiltersQueryParamFactory from '@State/time-filter-query-params-factory';

export const requestsApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getRequests: builder.query({
      providesTags: () => [API_TAGS.REQUESTS],
      query: ({
        projectUuid, from, to, routes, tags, requestTypes, page, limit,
      }) => {
        const params = timeFiltersQueryParamFactory({ from, to, init: {} });

        routes.forEach((route) => {
          params.append('routes', route);
        });

        requestTypes.forEach((requestType) => {
          params.append('requestType', requestType);
        });

        appendTagsToParams(params, tags);

        params.append('_page', page);
        params.append('_limit', limit);

        return ({
          url: `/projects/${projectUuid}/requests?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getRequestById: builder.query({
      providesTags: () => [API_TAGS.REQUESTS],
      query: ({ projectUuid, requestUuid }) => ({
        url: `/projects/${projectUuid}/requests/${requestUuid}`,
        method: 'get',
      }),
    }),
  }),
});

export const { useGetRequestsQuery,
  useGetRequestByIdQuery } = requestsApiSlice;
