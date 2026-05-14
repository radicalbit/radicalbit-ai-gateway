import { API_TAGS, apiService } from '@Src/store/apis';

export const projectsApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getProjects: builder.query({
      providesTags: () => [API_TAGS.PROJECTS],
      query: () => ({
        url: '/projects',
        method: 'get',
      }),
    }),

    getProject: builder.query({
      providesTags: (result, error, uuid) => [API_TAGS.PROJECTS, { type: API_TAGS.PROJECTS, id: uuid }],
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
          return [API_TAGS.PROJECTS];
        }

        return [];
      },
    }),
  }),
});

export const { useGetProjectsQuery, useGetProjectQuery, useCreateProjectMutation } = projectsApiSlice;

export const selectors = {};
