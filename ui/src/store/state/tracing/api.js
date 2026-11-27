import { API_TAGS, apiService } from '@Src/store/apis';
import { appendTagsToParams } from '@State/tags-query-params-factory';
import timeFiltersQueryParamFactory from '@State/time-filter-query-params-factory';

export const tracingApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getTracesChart: builder.query({
      providesTags: () => [API_TAGS.TRACING],
      query: ({ projectUuid, from, to, routes, tags }) => {
        const init = {};

        const params = timeFiltersQueryParamFactory({ from, to, init });

        if (routes && routes.length > 0) {
          routes.forEach((route) => {
            params.append('routes', route);
          });
        }

        appendTagsToParams(params, tags);

        return ({
          url: `/projects/${projectUuid}/traces/chart?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getTraceLatencies: builder.query({
      providesTags: () => [API_TAGS.TRACING],
      query: ({ projectUuid, from, to, routes, tags }) => {
        const init = {};

        const params = timeFiltersQueryParamFactory({ from, to, init });

        if (routes && routes.length > 0) {
          routes.forEach((route) => {
            params.append('routes', route);
          });
        }

        appendTagsToParams(params, tags);

        return ({
          url: `/projects/${projectUuid}/traces/latencies?${params.toString()}`,
          method: 'get',
        });
      },
    }),

    getSpanLatencies: builder.query({
      providesTags: () => [API_TAGS.TRACING],
      query: ({
        projectUuid, from, to, routes, tags, includeOthers = false, grouped = false,
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

        appendTagsToParams(params, tags);

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
  }),
});

export const { useGetTracesChartQuery, useGetTraceLatenciesQuery, useGetSpanLatenciesQuery, useGetTraceByIdQuery, useGetSpanByIdQuery } = tracingApiSlice;

export const selectors = {};
