import { API_TAGS, apiService } from '@Src/store/apis';

export const featureFlagsApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getFeatureFlags: builder.query({
      providesTags: () => [API_TAGS.FEATURE_FLAGS],
      query: () => ({
        url: '/configs/runtime',
        method: 'get',
      }),
      // queryFn: () => ({ data: { enableRouteAuthentication: false }, error: undefined }),
    }),
  }),
});

export const { useGetFeatureFlagsQuery } = featureFlagsApiSlice;

export const selectors = {};
