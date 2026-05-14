import { API_TAGS, apiService } from '@Src/store/apis';

export const configurationsApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getAppConfigurations: builder.query({
      providesTags: () => [API_TAGS.APP_CONFIG],
      query: () => ({
        url: '/configs/application',
        method: 'get',
      }),
    }),
  }),
});

export const { useGetAppConfigurationsQuery } = configurationsApiSlice;

export const selectors = {};
