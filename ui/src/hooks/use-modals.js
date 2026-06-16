import { useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

const _handleQueryString = (search, key, value) => {
  const queryString = search.startsWith('?') ? search.slice(1) : search;
  const params = new URLSearchParams(queryString);

  if (value !== undefined && value !== null) {
    params.set(key, value);
  } else {
    params.delete(key);
  }

  // Return the new query string WITHOUT the leading '?'
  return params.toString();
};

const modals = {
  ADD_GROUP_TO_KEY: 'ADD_GROUP_TO_KEY',
  ADD_GROUPS_TO_ROUTE: 'ADD_GROUPS_TO_ROUTE',
  ADD_KEYS_TO_GROUP: 'ADD_KEYS_TO_GROUP',
  ADD_ROUTES_TO_GROUP: 'ADD_ROUTES_TO_GROUP',
  CREATE_GROUPS: 'CREATE_GROUPS',
  CREATE_KEY: 'CREATE_KEY',
  CREATE_PROJECT: 'CREATE_PROJECT',
  DELETE_GROUP_WITH_ASSOCIATED_ITEMS: 'DELETE_GROUP_WITH_ASSOCIATED_ITEMS',
  DELETE_KEY_WITH_GROUPS: 'DELETE_KEY_WITH_GROUPS',
  EDIT_GROUP: 'EDIT_GROUP',
  EDIT_KEY: 'EDIT_KEY',
  EDIT_PROJECT_CONFIG: 'EDIT_PROJECT_CONFIG',
  ROUTE_ANALYTICS: 'ROUTE_ANALYTICS',
  TRACE_DETAIL: 'TRACE_DETAIL',
  QUERY_NAME: 'modal',
};

const _getModal = (search) => {
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search);
  const modalBase64 = params.get('modal');

  if (!modalBase64) return undefined;

  try {
    const jsonString = atob(modalBase64);

    return JSON.parse(jsonString);
  } catch (e) {
    console.error('Failed to decode or parse modal param:', e);
    return undefined;
  }
};

const useModals = () => {
  const navigate = useNavigate();
  const { search } = useLocation();

  const showModal = useCallback(
    (modalName, data = {}) => {
      // FIXME: with react-router-dom v6 probably we can use useSearcParams and remove the window.location.search
      const parsedSearch = _handleQueryString(window.location.search, modals.QUERY_NAME, btoa(JSON.stringify({ modalName, data })));

      navigate(`?${parsedSearch}`);
    },
    [navigate],
  );

  const hideModal = useCallback(() => {
    // FIXME: with react-router-dom v6 probably we can use useSearcParams and remove the window.location.search
    const parsedSearch = _handleQueryString(window.location.search, modals.QUERY_NAME);

    navigate(`?${parsedSearch}`);
  }, [navigate]);

  const modalPayload = _getModal(search);

  return { showModal, hideModal, modalPayload };
};

export default useModals;
export { modals };
