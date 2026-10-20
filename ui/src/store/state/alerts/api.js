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

    getAlertsHistory: builder.query({
      query: () => ({
        url: '/rule/history',
        method: 'get',
      }),
    }),

    getAlertHistory: builder.query({
      query: (uuid) => ({
        url: `/rule/${uuid}/history`,
        method: 'get',
      }),
    }),

    getCredentialAlertableEvents: builder.query({
      query: ({ credentialUuid } = {}) => ({
        url: `/keys/${credentialUuid}/alertable-events`,
        method: 'get',
      }),
    }),

    getProjectAlertableEvents: builder.query({
      query: ({ projectUuid } = {}) => ({
        url: `/projects/${projectUuid}/alertable-events`,
        method: 'get',
      }),
    }),

    getAlertableEvents: builder.query({
      query: ({ projectUuid, routeName } = {}) => ({
        url: `/projects/${projectUuid}/routes/${routeName}/alertable-events`,
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
        method: 'patch',
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
  useGetAlertsHistoryQuery,
  useGetAlertHistoryQuery,
  useGetAlertableEventsQuery,
  useGetCredentialAlertableEventsQuery,
  useGetProjectAlertableEventsQuery,
  useCreateAlertMutation,
  useToggleAlertMutation,
  useEditAlertMutation,
  useDeleteAlertMutation,
} = alertsApiSlice;

export const selectors = {};
