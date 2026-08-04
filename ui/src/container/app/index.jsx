import { useInitDarkMode, useIsDarkMode, useSetDarkMode } from '@Components/dark-mode/hooks';
import RedirectingToLogin from '@Components/error-page/redirecting-to-login';
import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import Logo from '@Components/logo';
import ModalsProvider from '@Components/modals/modals-provider';
import BottomMenu from '@Container/app/bottom-menu';
import MainHeaderContentSwitch from '@Container/app/header-content-switch';
import MainContentSwitch from '@Container/app/main-content-switch';
import RightColumnHeaderAltContentSwitch from '@Container/app/right-alt-content-switch';
import RightColumnSwitch from '@Container/app/right-column-switch';
import SecondaryHeaderContentSwitch from '@Container/app/secondary-column-header-content-switch';
import SecondaryContentSwitch from '@Container/app/secondary-column-main-content-switch';
import { createRoutes } from '@Container/layout';
import { PathsEnum } from '@Src/constants';
import { useContextConfigurationFromUrlEffect } from '@State/context-configuration/hooks';
import { useGetFeatureFlagsQuery } from '@State/feature-flags/api';
import { actions as layoutActions, selectors as layoutSelectors } from '@State/layout';
import { useNotification } from '@State/notification/hooks';
import '@Styles/index.less';
import '@Styles/tailwind.less';
import { Board, Layout } from '@radicalbit/radicalbit-design-system';
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

function App() {
  const { isLoading, isSuccess, isError, error } = useGetFeatureFlagsQuery();

  if (isLoading) {
    return false;
  }

  if (isError) {
    if (error?.status === 401) {
      return (
        <div className="h-screen">
          <Board height="100%" main={<RedirectingToLogin />} />
        </div>
      );
    }

    return (
      <div className="h-screen">
        <Board height="100%" main={<SomethingWentWrong />} />
      </div>
    );
  }

  if (!isSuccess) {
    return false;
  }

  return <AppInner />;
}

function AppInner() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  useNotification();
  useContextConfigurationFromUrlEffect();
  const hasHeaderContentDark = useSelector(
    layoutSelectors.selectHasHeaderContentDark,
  );
  const hasHeaderLeftContentDark = useSelector(
    layoutSelectors.selectHasHeaderLeftContentDark,
  );
  const hasHeaderSecondaryContentDark = useSelector(
    layoutSelectors.selectHasHeaderSecondaryContentDark,
  );
  const hasLeftContentDark = useSelector(
    layoutSelectors.selectHasLeftContentDark,
  );
  const hasMainContentDark = useSelector(
    layoutSelectors.selectHasMainContentDark,
  );
  const hasSecondaryContentDark = useSelector(
    layoutSelectors.selectHasSecondaryContentDark,
  );
  const hasRightContentDark = useSelector(
    layoutSelectors.selectHasRightContentDark,
  );

  const hasHeader = useSelector(layoutSelectors.selectHasHeader);
  const isSecondaryColumn = useSelector(
    layoutSelectors.selectHasSecondaryColumn,
  );
  const isRightColumn = useSelector(
    layoutSelectors.selectHasRightColumn,
  );
  const isLeftColumnCollapsed = useSelector(
    layoutSelectors.selectHasLeftColumnCollapsed,
  );
  const hasSecondaryColumnCollapsed = useSelector(
    layoutSelectors.selectHasSecondaryColumnCollapsed,
  );

  const hasSecondaryColumn = isSecondaryColumn;
  const hasLeftColumnCollapsed = isLeftColumnCollapsed;

  const hasRightColumn = isRightColumn;

  const showBottomDrawerOnHover = useSelector(
    layoutSelectors.selectShowBottomDrawerOnHover,
  );

  const handleToggleCollapseLeftColumn = () => {
    dispatch(layoutActions.toggleCollapseLeftColumn());
  };

  const handleToggleCollapseSecondaryColumn = () => {
    dispatch(layoutActions.toggleCollapseSecondaryColumn());
  };

  const goToHomePage = () => {
    navigate('/');
  };

  useNavigateNavBarWithKeyboard();
  useSwitchLightAndDarkModeWithKeyboard();

  return (
    <>
      <Layout
        hasHeader={hasHeader}
        hasLeftColumn
        hasMainColumn
        hasOverallTop={false}
        hasRightColumn={hasRightColumn}
        hasSecondaryColumn={hasSecondaryColumn}
        left={{
          hasHeaderLeftContentDark,
          hasLeftColumnCollapsed,
          hasLeftContentDark,
          leftColumnHeaderAltContent: (
            <Logo onClick={goToHomePage} title="Radicalbit" />
          ),
          mainMenu: createRoutes({ hasLeftColumnCollapsed, currentPath: pathname }),
          onLeftColumnCollapse: handleToggleCollapseLeftColumn,
          bottomMenu: <BottomMenu />,
        }}
        main={{
          hasMainContentDark,
          hasHeaderContentDark,
          headerContent: <MainHeaderContentSwitch />,
          mainContent: <MainContentSwitch />,
          showBottomDrawerOnHover,
        }}
        right={{
          rightContent: <RightColumnSwitch />,
          hasHeaderRightContentDark: hasRightContentDark,
          hasRightColumnCollapsed: false,
          rightColumnHeaderAltContent: <RightColumnHeaderAltContentSwitch />,
          hasRightContentDark,
        }}
        secondary={{
          headerContent: <SecondaryHeaderContentSwitch />,
          mainContent: <SecondaryContentSwitch />,
          onSecondaryColumnCollapse: handleToggleCollapseSecondaryColumn,
          hasHeaderSecondaryContentDark,
          hasSecondaryColumnCollapsed,
          hasSecondaryContentDark,
          hasSecondaryColumn,
        }}
      />

      <ModalsProvider />
    </>
  );
}

const useNavigateNavBarWithKeyboard = () => {
  const navigate = useNavigate();

  useEffect(() => {
    const handleKeyDown = (e) => {
      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;

      if ((isMac && e.ctrlKey && e.code === 'Digit1')) {
        e.preventDefault();
        navigate(`/${PathsEnum.PROJECTS}`);
      }

      if ((isMac && e.ctrlKey && e.code === 'Digit2')) {
        e.preventDefault();
        navigate(`/${PathsEnum.CONFIGURATIONS}`);
      }

      if ((isMac && e.ctrlKey && e.code === 'Digit3')) {
        e.preventDefault();
        navigate(`/${PathsEnum.ROUTES}`);
      }

      if ((isMac && e.ctrlKey && e.code === 'Digit4')) {
        e.preventDefault();
        navigate(`/${PathsEnum.USAGE}`);
      }

      if ((isMac && e.ctrlKey && e.code === 'Digit5')) {
        e.preventDefault();
        navigate(`/${PathsEnum.TRACING}`);
      }

      if ((isMac && e.ctrlKey && e.code === 'Digit6')) {
        e.preventDefault();
        navigate(`/${PathsEnum.GROUPS}`);
      }

      if ((isMac && e.ctrlKey && e.code === 'Digit7')) {
        e.preventDefault();
        navigate(`/${PathsEnum.CREDENTIALS}`);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [navigate]);
};

function useSwitchLightAndDarkModeWithKeyboard() {
  const isDarkMode = useIsDarkMode();
  const { enableDarkMode, enableLightMode } = useSetDarkMode();

  useInitDarkMode();

  useEffect(() => {
    function handleKeyDown(event) {
      if (event.ctrlKey && event.shiftKey && event.code === 'KeyL') {
        event.preventDefault();

        if (isDarkMode) {
          enableLightMode();
        } else {
          enableDarkMode();
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [enableDarkMode, enableLightMode, isDarkMode]);
}

export default App;
