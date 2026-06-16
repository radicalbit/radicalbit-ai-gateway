import { API_TAGS, apiService } from '@Src/store/apis';

const LIST_ID = 'LIST';

export const projectsApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getProjects: builder.query({
      providesTags: () => [{ type: API_TAGS.PROJECTS, id: LIST_ID }],
      query: (params = {}) => {
        const searchParams = new URLSearchParams();

        Object.entries(params).forEach(([key, value]) => {
          if (value !== undefined && value !== null && value !== '') {
            searchParams.set(key, value);
          }
        });

        const queryString = searchParams.toString();

        return {
          url: queryString ? `/projects?${queryString}` : '/projects',
          method: 'get',
        };
      },
    }),

    getProject: builder.query({
      providesTags: (result, error, uuid) => [{ type: API_TAGS.PROJECTS, id: uuid }],
      query: (uuid) => ({
        url: `/projects/${uuid}`,
        method: 'get',
      }),
    }),

    verifyProject: builder.query({
      providesTags: (result, error, uuid) => [{ type: API_TAGS.PROJECTS, id: `verify-${uuid}` }],
      query: (uuid) => ({
        url: `/projects/${uuid}`,
        method: 'get',
      }),
    }),

    createProject: builder.mutation({
      query: ({ data }) => ({
        url: '/projects',
        method: 'post',
        data,
      }),
      invalidatesTags: (result) => {
        if (result) {
          return [{ type: API_TAGS.PROJECTS, id: LIST_ID }];
        }

        return [];
      },
    }),

    deleteProject: builder.mutation({
      query: ({ uuid }) => ({
        url: `/projects/${uuid}`,
        method: 'delete',
      }),
      invalidatesTags: (result, error) => {
        if (!error) {
          return [{ type: API_TAGS.PROJECTS, id: LIST_ID }];
        }

        return [];
      },
    }),

    getConfig: builder.query({
      providesTags: (result, error, { configUuid }) => [{ type: API_TAGS.PROJECTS, id: `config-${configUuid}` }],
      query: ({ projectUuid, configUuid }) => ({
        url: `/projects/${projectUuid}/configs/${configUuid}`,
        method: 'get',
      }),
    }),

    generateConfig: builder.mutation({
      query: ({ projectUuid, configUuid, data }) => ({
        url: `/projects/${projectUuid}/configs/${configUuid}/generate-config`,
        method: 'post',
        data,
      }),
    }),

    updateConfig: builder.mutation({
      query: ({ projectUuid, configUuid, data }) => ({
        url: `/projects/${projectUuid}/configs/${configUuid}`,
        method: 'patch',
        data,
      }),
      invalidatesTags: (result, error, { projectUuid }) => {
        if (result) {
          return [
            { type: API_TAGS.PROJECTS, id: LIST_ID },
            { type: API_TAGS.PROJECTS, id: projectUuid },
          ];
        }

        return [];
      },
    }),

    approveConfig: builder.mutation({
      query: ({ projectUuid, configUuid }) => ({
        url: `/projects/${projectUuid}/configs/${configUuid}/approve`,
        method: 'patch',
      }),
      invalidatesTags: (result, error, { projectUuid }) => {
        if (result) {
          return [
            { type: API_TAGS.PROJECTS, id: LIST_ID },
            { type: API_TAGS.PROJECTS, id: projectUuid },
          ];
        }

        return [];
      },
    }),

    cancelApproval: builder.mutation({
      query: ({ projectUuid, configUuid }) => ({
        url: `/projects/${projectUuid}/configs/${configUuid}/cancel-approval`,
        method: 'patch',
      }),
      invalidatesTags: (result, error, { projectUuid }) => {
        if (result) {
          return [
            { type: API_TAGS.PROJECTS, id: LIST_ID },
            { type: API_TAGS.PROJECTS, id: projectUuid },
          ];
        }

        return [];
      },
    }),

    serveConfig: builder.mutation({
      query: ({ projectUuid, configUuid }) => ({
        url: `/projects/${projectUuid}/configs/${configUuid}/serve`,
        method: 'patch',
      }),
      invalidatesTags: (result, error, { projectUuid }) => {
        if (result) {
          return [
            { type: API_TAGS.PROJECTS, id: LIST_ID },
            { type: API_TAGS.PROJECTS, id: projectUuid },
          ];
        }

        return [];
      },
    }),

    unserveConfig: builder.mutation({
      query: ({ projectUuid, configUuid }) => ({
        url: `/projects/${projectUuid}/configs/${configUuid}/unserve`,
        method: 'patch',
      }),
      invalidatesTags: (result, error, { projectUuid }) => {
        if (result) {
          return [
            { type: API_TAGS.PROJECTS, id: LIST_ID },
            { type: API_TAGS.PROJECTS, id: projectUuid },
          ];
        }

        return [];
      },
    }),
  }),
});

export const {
  useGetProjectsQuery,
  useGetProjectQuery,
  useVerifyProjectQuery,
  useCreateProjectMutation,
  useDeleteProjectMutation,
  useGetConfigQuery,
  useGenerateConfigMutation,
  useUpdateConfigMutation,
  useApproveConfigMutation,
  useCancelApprovalMutation,
  useServeConfigMutation,
  useUnserveConfigMutation,
} = projectsApiSlice;

export const selectors = {};
