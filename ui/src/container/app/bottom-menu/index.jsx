import { Menu } from '@radicalbit/radicalbit-design-system';
// import { useGetDarkLightModeItem } from './hooks';

export default function BottomMenu() {
  // const darkLightModeItem = useGetDarkLightModeItem();

  // const items = [darkLightModeItem].filter(Boolean);
  const items = [];

  return (
    <Menu
      items={items}
      selectedKeys={[]}
      style={{ background: 'transparent' }}
    />
  );
}
