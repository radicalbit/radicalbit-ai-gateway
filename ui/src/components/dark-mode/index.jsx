import Lucide from '@Components/lucide';
import { Tooltip } from '@radicalbit/radicalbit-design-system';
import { CollapsedTitle } from '@Container/layout';
import { useInitDarkMode, useIsDarkMode } from '@Components/dark-mode/hooks';
import { Moon, Sun } from 'lucide-react';

function DarkMode({ darkActions, lightActions }) {
  const isDarkMode = useIsDarkMode();

  useInitDarkMode(darkActions, lightActions);

  if (isDarkMode) {
    return (
      <Tooltip placement="bottomLeft" title={<TooltipTitle title="Light mode" />}>
        <Lucide icon={Sun} />
      </Tooltip>
    );
  }

  return (
    <Tooltip placement="bottomLeft" title={<TooltipTitle title="Dark mode" />}>
      <Lucide icon={Moon} />
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
