import { API_TAGS, apiService } from '@Src/store/apis';

export const keysApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getKeys: builder.query({
      providesTags: () => [API_TAGS.KEYS],
      query: ({ onlyUnassigned = false } = {}) => {
        const params = new URLSearchParams();
        params.append('include_groups', 'true');

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
        url: `/keys/${uuid}?include_groups=true`,
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
  }),
});

export const {
  useGetKeysQuery,
  useGetAssociableGroupsByKeyQuery,
  useGetKeyQuery,
  useCreateKeyMutation,
  useEditKeyMutation,
  useAddGroupToKeyMutation,
  useDeleteKeyMutation,
} = keysApiSlice;

export const selectors = {};
