import axios from 'axios';
import { API_BASE_URL } from './config';

export const customBaseQuery = () => async ({ baseUrl, url, method, data, headers = {} }) => {
  const resolvedBaseUrl = baseUrl !== undefined ? baseUrl : API_BASE_URL;

  try {
    const result = await axios({
      url: `${resolvedBaseUrl}${url}`,
      method,
      data,
      headers,
      withCredentials: true,
    });

    if (result.headers['x-total-count'] !== undefined) {
      return {
        data: {
          items: result.data,
          xTotalCount: +result.headers['x-total-count'],
        },
      };
    }

    return { data: result.data };
  } catch (axiosError) {
    const err = axiosError;

    if (err.response?.status === 401 && !url.startsWith('/auth')) {
      window.location.href = `${window.location.origin}/auth/login`;
      return {
        error: { status: 401, data: err.response?.data },
      };
    }

    return {
      error: { status: err.response?.status, data: err.response?.data, withCredentials: true },
    };
  }
};
