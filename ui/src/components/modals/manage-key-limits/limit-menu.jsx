import Lucide from '@Components/lucide';
import focusDeleteQuestion from '@Components/limits/focus-delete-question';
import focusLimitRow from '@Components/limits/focus-limit-row';
import { LIMIT_CATEGORY_LABELS, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import { formatLimitWindow } from '@Components/limits/helpers';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, Dropdown, Tooltip } from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical } from 'lucide-react';
import { useRef, useState } from 'react';
import { ScreenEnum } from './schema';

const MENU_TRIGGER = ['hover', 'click'];

function LimitMenu({ limit }) {
  const buttonRef = useRef(null);

  const { writeAll } = useFormbitContext();

  const [isOpenedByKeyboard, setIsOpenedByKeyboard] = useState(false);

  const limitUuid = limit?.uuid;
  const label = `${LIMIT_CATEGORY_LABELS[limit?.category]} ${formatLimitWindow(limit?.windowSize)} · ${WINDOW_TYPE_LABELS[limit?.algorithm]}`;

  const handleOnEdit = () => {
    const row = {
      algorithm: limit?.algorithm, category: limit?.category, rowKey: limitUuid, value: limit?.value, windowSize: limit?.windowSize,
    };

    writeAll([['limits', [row]], ['__metadata.limitUuid', limitUuid], ['__metadata.screen', ScreenEnum.EDIT]]);
    focusLimitRow(0);
  };

  const handleOnDelete = () => {
    writeAll([['__metadata.limitUuid', limitUuid], ['__metadata.screen', ScreenEnum.DELETE]]);
    focusDeleteQuestion();
  };

  const items = [
    { key: 'edit', label: 'Edit', onClick: handleOnEdit },
    { key: 'delete', label: 'Delete', onClick: handleOnDelete },
  ];

  const handleOnOpenChange = (isOpen) => {
    const { activeElement } = document;
    const isFocusLost = activeElement === document.body || activeElement?.closest('.ant-dropdown');

    if (!isOpen) {
      setIsOpenedByKeyboard(false);
    }

    if (!isOpen && isFocusLost) {
      buttonRef.current?.focus();
    }
  };

  const handleOnKeyDown = (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      setIsOpenedByKeyboard(true);
    }
  };

  return (
    <Tooltip title="More actions">
      <Dropdown autoFocus={isOpenedByKeyboard} destroyOnHidden menu={{ items }} onOpenChange={handleOnOpenChange} trigger={MENU_TRIGGER}>
        <Button aria-label={`More actions for limit ${label}`} data-limit-menu={limitUuid} onKeyDown={handleOnKeyDown} ref={buttonRef} type="text">
          <Lucide icon={EllipsisVertical} />
        </Button>
      </Dropdown>
    </Tooltip>
  );
}

export default LimitMenu;
