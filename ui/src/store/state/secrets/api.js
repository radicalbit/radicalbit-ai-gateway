import { API_TAGS, apiService } from '@Src/store/apis';

export const secretsApiSlice = apiService.injectEndpoints({
  endpoints: (builder) => ({
    getSecrets: builder.query({
      providesTags: () => [API_TAGS.SECRETS],
      query: ({ page, limit } = {}) => {
        const params = new URLSearchParams();

        if (page !== undefined) {
          params.append('_page', page);
        }

        if (limit !== undefined) {
          params.append('_limit', limit);
        }

        return {
          url: `/secrets?${params.toString()}`,
          method: 'get',
        };
      },
    }),
  }),
});

export const { useGetSecretsQuery } = secretsApiSlice;

export const selectors = {};
