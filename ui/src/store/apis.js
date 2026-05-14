import { customBaseQuery } from '@Api/utils';
import { createApi } from '@reduxjs/toolkit/query/react';

export const API_TAGS = {
  APP_CONFIG: 'APP_CONFIG',
  FEATURE_FLAGS: 'FEATURE_FLAGS',
  IDP_GROUPS: 'IDP_GROUPS',
  GROUPS: 'GROUPS',
  KEYS: 'KEYS',
  METRICS: 'METRICS',
  PROJECTS: 'PROJECTS',
  USAGE: 'USAGE',
  ROUTES: 'ROUTES',
  TRACING: 'TRACING',
};

export const apiService = createApi({
  reducerPath: 'api',
  baseQuery: customBaseQuery(),
  tagTypes: [API_TAGS.ROUTES],
  endpoints: () => ({}),
});
