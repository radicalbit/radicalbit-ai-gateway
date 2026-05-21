import DarkMode from '@Components/dark-mode';
import { useIsDarkMode, useSetDarkMode } from '@Components/dark-mode/hooks';

const useGetDarkLightModeItem = () => {
  const isDarkMode = useIsDarkMode();
  const { enableDarkMode, enableLightMode } = useSetDarkMode();

  return {
    key: 'dark-mode',
    label: isDarkMode ? 'Light mode' : 'Dark mode',
    icon: <div className="ant-menu-item-icon"><DarkMode /></div>,
    onClick: () => {
      if (isDarkMode) {
        enableLightMode();
      } else {
        enableDarkMode();
      }
    },
  };
};

export { useGetDarkLightModeItem };
