import axios from 'axios';
import { API_BASE_URL } from './config';

const DEFAULT_DOWNLOAD_FILENAME = 'download.zip';

const parseFilenameFromContentDisposition = (contentDisposition) => {
  if (!contentDisposition) {
    return DEFAULT_DOWNLOAD_FILENAME;
  }

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1]);
  }

  const asciiMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
  if (asciiMatch?.[1]) {
    return asciiMatch[1];
  }

  return DEFAULT_DOWNLOAD_FILENAME;
};

export const customBaseQuery = () => async ({
  baseUrl, url, method, data, headers = {}, responseType,
}) => {
  const resolvedBaseUrl = baseUrl !== undefined ? baseUrl : API_BASE_URL;

  try {
    const result = await axios({
      url: `${resolvedBaseUrl}${url}`,
      method,
      data,
      headers,
      responseType,
      withCredentials: true,
    });

    if (responseType === 'blob') {
      const filename = parseFilenameFromContentDisposition(result.headers['content-disposition']);
      return { data: { blob: result.data, filename } };
    }

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
