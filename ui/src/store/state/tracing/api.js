import { API_TAGS, apiService } from '@Src/store/apis';
import timeFiltersQueryParamFactory from '@State/time-filter-query-params-factory';

export const tracingApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getTracesChart: builder.query({
      providesTags: () => [API_TAGS.TRACING],
      query: ({ projectUuid, from, to, routes }) => {
        const init = {};

        const params = timeFiltersQueryParamFactory({ from, to, init });

        if (routes && routes.length > 0) {
          routes.forEach((route) => {
            params.append('routes', route);
          });
        }

        return ({
          url: `/projects/${projectUuid}/traces/chart?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getTraceLatencies: builder.query({
      providesTags: () => [API_TAGS.TRACING],
      query: ({ projectUuid, from, to, routes }) => {
        const init = {};

        const params = timeFiltersQueryParamFactory({ from, to, init });

        if (routes && routes.length > 0) {
          routes.forEach((route) => {
            params.append('routes', route);
          });
        }

        return ({
          url: `/projects/${projectUuid}/traces/latencies?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getSpanLatencies: builder.query({
      providesTags: () => [API_TAGS.TRACING],
      query: ({
        projectUuid, from, to, routes, includeOthers = false, grouped = false,
      }) => {
        const init = {
          grouped,
          include_others: includeOthers,
        };

        const params = timeFiltersQueryParamFactory({ from, to, init });

        if (routes && routes.length > 0) {
          routes.forEach((route) => {
            params.append('routes', route);
          });
        }

        return ({
          url: `/projects/${projectUuid}/traces/spans/latencies?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getTraceById: builder.query({
      providesTags: () => [API_TAGS.TRACING],
      query: ({ projectUuid, traceId }) => ({
        url: `/projects/${projectUuid}/traces/${traceId}`,
        method: 'get',
      }),
    }),

    getSpanById: builder.query({
      providesTags: () => [API_TAGS.TRACING],
      query: ({ projectUuid, traceId, spanId }) => ({
        url: `/projects/${projectUuid}/traces/${traceId}/spans/${spanId}`,
        method: 'get',
      }),
    }),

    getTraces: builder.query({
      providesTags: () => [API_TAGS.TRACING],
      query: ({
        projectUuid, from, to, routes, page, limit,
      }) => {
        const init = {};

        const params = timeFiltersQueryParamFactory({ from, to, init });

        if (routes && routes.length > 0) {
          routes.forEach((route) => {
            params.append('routes', route);
          });
        }

        if (page !== undefined) {
          params.append('_page', page);
        }

        if (limit !== undefined) {
          params.append('_limit', limit);
        }

        return ({
          url: `/projects/${projectUuid}/traces?${params.toString()}`,
          method: 'get',
        });
      },
    }),
  }),
});

export const {
  useGetTracesChartQuery, useGetTraceLatenciesQuery, useGetSpanLatenciesQuery, useGetTraceByIdQuery, useGetSpanByIdQuery, useGetTracesQuery,
} = tracingApiSlice;

export const selectors = {};
