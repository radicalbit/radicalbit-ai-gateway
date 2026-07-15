import { API_TAGS, apiService } from '@Src/store/apis';

const MOCKED_ALERTS = [
  {
    uuid: '9f1c2e0a-3b4d-4e5f-8a90-1b2c3d4e5f60',
    name: 'PII guardrail alert',
    description: 'Notify security team on PII detection',
    project: 'Progetto 1',
    route: 'openai-prod',
    scope: 'route',
    event: 'guardrail-input-pii',
    timeAggregation: 'instant',
    channel: 'email',
    recipients: ['security@example.com', 'ops@example.com'],
    enabled: true,
    disabledReason: null,
    createdAt: '2026-07-15T10:12:00Z',
  },
  {
    uuid: 'a1b2c3d4-0000-0000-0000-000000000001',
    name: 'Toxicity guardrail alert',
    description: null,
    project: 'Progetto 2',
    route: 'anthropic-prod',
    scope: 'route',
    event: 'guardrail-input-toxicity',
    timeAggregation: 'instant',
    channel: 'email',
    recipients: ['ops@example.com'],
    enabled: false,
    disabledReason: 'The event is no longer valid for the current route configuration',
    createdAt: '2026-07-14T08:00:00Z',
  },
];

const MOCKED_ALERTABLE_EVENTS = {
  guardrail: [
    { event: 'guardrail-input-pii', label: 'Guardrail: PII (input)' },
    { event: 'guardrail-input-toxicity', label: 'Guardrail: Toxicity (input)' },
  ],
  caching: [
    { event: 'cache-exact', label: 'Caching: exact match' },
  ],
  fallback: [
    { event: 'fallback-triggered', label: 'Fallback: triggered' },
  ],
};

export const alertsApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getAlerts: builder.query({
      providesTags: () => [API_TAGS.ALERTS],
      queryFn: () => ({ data: MOCKED_ALERTS }),
    }),

    getAlert: builder.query({
      providesTags: (result) => [`${API_TAGS.ALERTS}-${result?.uuid}`],
      queryFn: (uuid) => {
        const alert = MOCKED_ALERTS.find(({ uuid: alertUuid }) => alertUuid === uuid);

        if (!alert) {
          return { error: { status: 404, data: 'Alert rule not found' } };
        }

        return { data: alert };
      },
    }),

    getAlertableEvents: builder.query({
      queryFn: () => ({ data: MOCKED_ALERTABLE_EVENTS }),
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
