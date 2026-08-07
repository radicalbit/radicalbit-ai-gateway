import { API_TAGS, apiService } from '@Src/store/apis';

export const alertsApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getAlerts: builder.query({
      query: () => ({
        url: '/rule',
        method: 'get',
      }),
      providesTags: () => [API_TAGS.ALERTS],
    }),

    getAlert: builder.query({
      query: (uuid) => ({
        url: `/rule/${uuid}`,
        method: 'get',
      }),
      providesTags: (result, error, uuid) => [`${API_TAGS.ALERTS}-${uuid}`],
    }),

    getAlertableEvents: builder.query({
      query: (routeId) => ({
        url: routeId ? `/routes/${routeId}/alertable-events` : '/alertable-events',
        method: 'get',
      }),
    }),

    toggleAlert: builder.mutation({
      query: ({ uuid, enabled }) => ({
        url: `/rule/${uuid}/enabled`,
        method: 'patch',
        data: { enabled },
      }),
      invalidatesTags: (result, error, { uuid }) => {
        if (!error) {
          return [`${API_TAGS.ALERTS}-${uuid}`, API_TAGS.ALERTS];
        }

        return [];
      },
    }),

    createAlert: builder.mutation({
      query: ({ data }) => ({
        url: '/rule',
        method: 'post',
        data,
      }),
      invalidatesTags: (result, error) => {
        if (!error) {
          return [API_TAGS.ALERTS];
        }

        return [];
      },
    }),

    editAlert: builder.mutation({
      query: ({ uuid, data }) => ({
        url: `/rule/${uuid}`,
        method: 'put',
        data,
      }),
      invalidatesTags: (result, error, { uuid }) => {
        if (!error) {
          return [`${API_TAGS.ALERTS}-${uuid}`, API_TAGS.ALERTS];
        }

        return [];
      },
    }),

    deleteAlert: builder.mutation({
      query: ({ uuid }) => ({
        url: `/rule/${uuid}`,
        method: 'delete',
      }),
      invalidatesTags: (result, error) => {
        if (!error) {
          return [API_TAGS.ALERTS];
        }

        return [];
      },
    }),
  }),
});

export const {
  useGetAlertsQuery,
  useGetAlertQuery,
  useGetAlertableEventsQuery,
  useCreateAlertMutation,
  useToggleAlertMutation,
  useEditAlertMutation,
  useDeleteAlertMutation,
} = alertsApiSlice;

export const selectors = {};
