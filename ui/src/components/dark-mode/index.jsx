import Lucide from '@Components/lucide';
import { Tooltip } from '@radicalbit/radicalbit-design-system';
import { CollapsedTitle } from '@Container/layout';
import { useInitDarkMode, useIsDarkMode, useSetDarkMode } from '@Components/dark-mode/hooks';
import { Moon, Sun } from 'lucide-react';

function DarkMode({ darkActions, lightActions }) {
  const isDarkMode = useIsDarkMode();
  const { enableDarkMode, enableLightMode } = useSetDarkMode(darkActions, lightActions);

  useInitDarkMode(darkActions, lightActions);

  if (isDarkMode) {
    return (
      <Tooltip placement="bottomLeft" title={<TooltipTitle title="Light mode" />}>
        <Lucide icon={Sun} onClick={enableDarkMode} />
      </Tooltip>
    );
  }

  return (
    <Tooltip placement="bottomLeft" title={<TooltipTitle title="Dark mode" />}>
      <Lucide icon={Moon} onClick={enableLightMode} />
    </Tooltip>

  );
}

function TooltipTitle({ title }) {
  return (
    <CollapsedTitle
      keys={{ mac: [{ label: 'Ctrl' }, { label: 'Shift' }, { label: 'L', shape: 'circle' }] }}
    >
      {title}
    </CollapsedTitle>
  );
}

export default DarkMode;
