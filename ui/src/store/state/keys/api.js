import { API_BASE_URL } from '@Api/config';
import { API_TAGS, apiService } from '@Src/store/apis';
import eventSourceWithBackoff from '@State/event-source-with-backoff';

const DEFAULT_CONSUMPTION_STATE = {
  consumption: null,
  isSseLoading: true,
  isSseError: false,
  isSseSuccess: false,
  sseErrorMessage: null,
};

export const keysApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getKeys: builder.query({
      providesTags: () => [API_TAGS.KEYS],
      query: ({ onlyUnassigned = false } = {}) => {
        const params = new URLSearchParams();
        params.append('include_groups', 'true');
        params.append('include_limits', 'true');

        if (onlyUnassigned) {
          params.append('only_unassigned', 'true');
        }

        return {
          url: `/keys?${params.toString()}`,
          method: 'get',
        };
      },
    }),

    getAssociableGroupsByKey: builder.query({
      providesTags: () => [API_TAGS.KEYS],
      query: ({ keyUuid }) => ({
        url: `/keys/${keyUuid}/associable-groups?include_routes=true&include_keys=true`,
        method: 'get',
      }),
    }),

    getKey: builder.query({
      providesTags: (result) => {
        const uuid = result?.uuid;

        return [`${API_TAGS.KEYS}-${uuid}`];
      },
      query: (uuid) => ({
        url: `/keys/${uuid}?include_groups=true&include_limits=true`,
        method: 'get',
      }),
    }),

    createKey: builder.mutation({
      query: ({ data }) => ({
        url: '/keys',
        method: 'post',
        data,
      }),
      invalidatesTags: (result) => {
        if (result) {
          return [API_TAGS.KEYS];
        }

        return [];
      },
    }),

    editKey: builder.mutation({
      query: ({ data, uuid }) => ({
        url: `/keys/${uuid}`,
        method: 'patch',
        data,
      }),
      invalidatesTags: (result) => {
        const { uuid } = result;

        if (result) {
          return [API_TAGS.KEYS, `${API_TAGS.KEYS}-${uuid}`];
        }

        return [];
      },
    }),

    addGroupToKey: builder.mutation({
      query: ({ data, keyUuid }) => ({
        url: `/keys/${keyUuid}/group?include_groups=true`,
        method: 'patch',
        data,
      }),
      invalidatesTags: (result, _, { data, keyUuid }) => {
        const groups = data?.groups || [];

        if (result) {
          return [
            API_TAGS.GROUPS,
            ...groups.map((groupUUID) => `${API_TAGS.GROUPS}-${groupUUID}`),
            API_TAGS.KEYS,
            `${API_TAGS.KEYS}-${keyUuid}`,
          ];
        }

        return [];
      },
    }),

    // Returns the credential with the new value in full, once, as on creation
    rotateKey: builder.mutation({
      query: ({ data, uuid }) => ({
        url: `/keys/${uuid}/rotation`,
        method: 'post',
        data,
      }),
      invalidatesTags: (result, _, { uuid }) => {
        if (result) {
          return [API_TAGS.KEYS, `${API_TAGS.KEYS}-${uuid}`];
        }

        return [];
      },
    }),

    endGracePeriod: builder.mutation({
      query: ({ uuid }) => ({
        url: `/keys/${uuid}/rotation`,
        method: 'delete',
      }),
      invalidatesTags: (result, _, { uuid }) => {
        if (result) {
          return [API_TAGS.KEYS, `${API_TAGS.KEYS}-${uuid}`];
        }

        return [];
      },
    }),

    createKeyLimits: builder.mutation({
      query: ({ data, uuid }) => ({
        url: `/keys/${uuid}/limits`,
        method: 'post',
        data,
      }),
      invalidatesTags: (result, _, { uuid }) => {
        if (result) {
          return [API_TAGS.KEYS, `${API_TAGS.KEYS}-${uuid}`, API_TAGS.ALERTS];
        }

        return [];
      },
    }),

    updateKeyLimitValue: builder.mutation({
      query: ({ data, limitUuid, uuid }) => ({
        url: `/keys/${uuid}/limits/${limitUuid}`,
        method: 'patch',
        data,
      }),
      invalidatesTags: (result, _, { uuid }) => {
        if (result) {
          return [API_TAGS.KEYS, `${API_TAGS.KEYS}-${uuid}`, API_TAGS.ALERTS];
        }

        return [];
      },
    }),

    deleteKeyLimit: builder.mutation({
      query: ({ limitUuid, uuid }) => ({
        url: `/keys/${uuid}/limits/${limitUuid}`,
        method: 'delete',
      }),
      invalidatesTags: (result, _, { uuid }) => {
        if (result) {
          return [API_TAGS.KEYS, `${API_TAGS.KEYS}-${uuid}`, API_TAGS.ALERTS];
        }

        return [];
      },
    }),

    deleteKey: builder.mutation({
      query: ({ uuid }) => ({
        url: `/keys/${uuid}?include_groups=true`,
        method: 'delete',
      }),
      invalidatesTags: (result, error) => {
        const gropus = result?.groups || [];

        if (!error) {
          return [
            API_TAGS.KEYS,
            API_TAGS.GROUPS,
            ...gropus.map(({ uuid: groupUUID }) => `${API_TAGS.GROUPS}-${groupUUID}`),
          ];
        }

        return [];
      },
    }),
    getKeyLimitsConsumptionStream: builder.query({
      keepUnusedDataFor: 0,
      queryFn: () => ({ data: DEFAULT_CONSUMPTION_STATE }),
      async onCacheEntryAdded(
        { keys },
        { cacheDataLoaded, cacheEntryRemoved, updateCachedData },
      ) {
        try {
          await cacheDataLoaded;

          const params = new URLSearchParams();
          [...keys].sort().forEach((uuid) => { params.append('keys', uuid); });

          const url = `${API_BASE_URL}/keys/limits/stream?${params.toString()}`;
          const subscription = eventSourceWithBackoff({
            url,
            onMessage: (parsed) => {
              updateCachedData(() => ({
                consumption: parsed,
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
                draft.sseErrorMessage = 'Unable to stream limits consumption';
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
  useGetKeyLimitsConsumptionStreamQuery,
  useGetKeysQuery,
  useGetAssociableGroupsByKeyQuery,
  useGetKeyQuery,
  useCreateKeyMutation,
  useEditKeyMutation,
  useAddGroupToKeyMutation,
  useDeleteKeyMutation,
  useRotateKeyMutation,
  useEndGracePeriodMutation,
  useCreateKeyLimitsMutation,
  useUpdateKeyLimitValueMutation,
  useDeleteKeyLimitMutation,
} = keysApiSlice;

export const selectors = {};
