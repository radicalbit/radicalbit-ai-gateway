import { API_TAGS, apiService } from '@Src/store/apis';

export const groupsApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getGroups: builder.query({
      providesTags: () => [API_TAGS.GROUPS],
      query: () => ({
        url: '/groups?include_routes=true&include_keys=true',
        method: 'get',
      }),
    }),

    getAssociableKeysByGroup: builder.query({
      providesTags: () => [API_TAGS.GROUPS],
      query: ({ groupUuid }) => ({
        url: `/groups/${groupUuid}/associable-keys`,
        method: 'get',
      }),
    }),

    getAssociableRoutesByGroup: builder.query({
      providesTags: () => [API_TAGS.GROUPS],
      query: ({ groupUuid, projectUuid }) => ({
        url: `/groups/${groupUuid}/projects/${projectUuid}/associable-routes`,
        method: 'get',
      }),
    }),

    getGroup: builder.query({
      providesTags: (result) => {
        const uuid = result?.uuid;

        return [`${API_TAGS.GROUPS}-${uuid}`];
      },
      query: (uuid) => ({
        url: `/groups/${uuid}?include_routes=true&include_keys=true`,
        method: 'get',
      }),
    }),

    createGroup: builder.mutation({
      query: ({ data }) => ({
        url: '/groups',
        method: 'post',
        data,
      }),
      invalidatesTags: (result) => {
        if (result) {
          return [API_TAGS.GROUPS];
        }

        return [];
      },
    }),

    editGroup: builder.mutation({
      query: ({ data, uuid }) => ({
        url: `/groups/${uuid}`,
        method: 'patch',
        data,
      }),
      invalidatesTags: (result, _error, args) => {
        const uuid = args?.uuid;

        if (result) {
          return [
            `${API_TAGS.GROUPS}-${uuid}`,
            API_TAGS.GROUPS,
          ];
        }

        return [];
      },
    }),

    deleteGroup: builder.mutation({
      query: ({ uuid }) => ({
        url: `/groups/${uuid}?include_routes=true&include_keys=true`,
        method: 'delete',
      }),
      invalidatesTags: (result, error) => {
        const keys = result?.keys || [];
        const routes = result?.routes || [];

        if (!error) {
          return [
            ...keys.map(({ uuid: keyUUID }) => `${API_TAGS.KEYS}-${keyUUID}`),
            API_TAGS.KEYS,
            API_TAGS.GROUPS,
            ...routes.map(({ name }) => `${API_TAGS.ROUTES}-${name}`),
            API_TAGS.ROUTES,
          ];
        }

        return [];
      },
    }),

    addKeysToGroup: builder.mutation({
      query: ({ data, uuid }) => ({
        url: `/groups/${uuid}/keys`,
        method: 'patch',
        data,
      }),
      invalidatesTags: (result, _, { data, uuid }) => {
        const keys = data?.keys || [];

        if (result) {
          return [
            API_TAGS.GROUPS,
            `${API_TAGS.GROUPS}-${uuid}`,
            API_TAGS.KEYS,
            ...keys.map((keyUUID) => `${API_TAGS.KEYS}-${keyUUID}`),
          ];
        }

        return [];
      },
    }),

    removeKeyFromGroup: builder.mutation({
      query: ({ uuid, keyUUID }) => ({
        url: `/groups/${uuid}/keys/${keyUUID}`,
        method: 'delete',
      }),
      invalidatesTags: (result, error, args) => {
        const groupUUID = args?.uuid;
        const keyUUID = args?.keyUUID;

        if (!error) {
          return [
            `${API_TAGS.KEYS}-${keyUUID}`,
            API_TAGS.KEYS,
            `${API_TAGS.GROUPS}-${groupUUID}`,
            API_TAGS.GROUPS,
          ];
        }

        return [];
      },
    }),

    addRoutesToGroup: builder.mutation({
      query: ({ data, uuid, projectUuid }) => ({
        url: `/groups/${uuid}/projects/${projectUuid}/routes`,
        method: 'patch',
        data,
      }),
      invalidatesTags: (result, _, { data, uuid }) => {
        const routes = data?.routes || [];

        if (result) {
          return [
            API_TAGS.GROUPS,
            `${API_TAGS.GROUPS}-${uuid}`,
            API_TAGS.ROUTES,
            ...routes.map((name) => `${API_TAGS.ROUTES}-${name}`),
          ];
        }

        return [];
      },
    }),

    removeRouteFromGroup: builder.mutation({
      query: ({ uuid, projectUuid, routeName }) => ({
        url: `/groups/${uuid}/projects/${projectUuid}/routes/${routeName}`,
        method: 'delete',
      }),
      invalidatesTags: (result, error, args) => {
        const groupUUID = args?.uuid;
        const routeName = args?.routeName;

        if (!error) {
          return [
            `${API_TAGS.ROUTES}-${routeName}`,
            API_TAGS.ROUTES,
            `${API_TAGS.GROUPS}-${groupUUID}`,
            API_TAGS.GROUPS,
          ];
        }

        return [];
      },
    }),
  }),
});

export const {
  useGetGroupsQuery,
  useGetAssociableKeysByGroupQuery,
  useGetAssociableRoutesByGroupQuery,
  useGetIdpGroupsQuery,
  useGetGroupQuery,
  useCreateGroupMutation,
  useEditGroupMutation,
  useDeleteGroupMutation,
  useAddKeysToGroupMutation,
  useRemoveKeyFromGroupMutation,
  useAddRoutesToGroupMutation,
  useRemoveRouteFromGroupMutation,
} = groupsApiSlice;

export const selectors = {};
