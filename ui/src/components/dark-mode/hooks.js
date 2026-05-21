import { EXPERIMENTAL_SET_DARK_MODE, EXPERIMENTAL_SET_LIGHT_MODE } from '@Container/layout/layout-provider/layout-provider-configuration';
import { useCallback, useEffect } from 'react';
import { useDispatch } from 'react-redux';

const useInitDarkMode = (darkActions = EXPERIMENTAL_SET_DARK_MODE, lightActions = EXPERIMENTAL_SET_LIGHT_MODE) => {
  const dispatch = useDispatch();

  useEffect(() => {
    const isDarkMode = window.localStorage.getItem('radicalbit-ai-gateway-enable-dark-mode');

    if (isDarkMode) {
      window.document.body.classList.add('dark');
    } else {
      window.document.body.classList.remove('dark');
    }

    if (isDarkMode) {
      darkActions.forEach((action) => dispatch(action()));
    } else {
      lightActions.forEach((action) => dispatch(action()));
    }
  }, [darkActions, dispatch, lightActions]);
};

const useSetDarkMode = (darkActions = EXPERIMENTAL_SET_DARK_MODE, lightActions = EXPERIMENTAL_SET_LIGHT_MODE) => {
  const dispatch = useDispatch();

  const enableDarkMode = useCallback(() => {
    window.localStorage.setItem('radicalbit-ai-gateway-enable-dark-mode', true);
    window.document.body.classList.add('dark');

    darkActions.forEach((action) => dispatch(action()));
  }, [darkActions, dispatch]);

  const enableLightMode = useCallback(() => {
    window.localStorage.removeItem('radicalbit-ai-gateway-enable-dark-mode');
    window.document.body.classList.remove('dark');

    lightActions.forEach((action) => dispatch(action()));
  }, [dispatch, lightActions]);

  return { enableDarkMode, enableLightMode };
};

const useIsDarkMode = () => window.document.body.classList.contains('dark');

export { useInitDarkMode, useIsDarkMode, useSetDarkMode };
