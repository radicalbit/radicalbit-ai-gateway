import Lucide from '@Components/lucide';
import focusConfirmQuestion from '@Components/limits/focus-confirm-question';
import focusLimitRow from '@Components/limits/focus-limit-row';
import { useFormbitContext } from '@radicalbit/formbit';
import { Button, Dropdown, Tooltip } from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical } from 'lucide-react';
import { useRef, useState } from 'react';
import { getBudgetLabel } from './helpers';
import { ScreenEnum, getEditRow } from './schema';

const MENU_TRIGGER = ['hover', 'click'];

function BudgetMenu({ limit }) {
  const buttonRef = useRef(null);

  const { writeAll } = useFormbitContext();

  const [isOpenedByKeyboard, setIsOpenedByKeyboard] = useState(false);

  const limitUuid = limit?.uuid;
  const label = getBudgetLabel(limit);

  const handleOnEdit = () => {
    writeAll([['limits', [getEditRow(limit)]], ['__metadata.limitUuid', limitUuid], ['__metadata.screen', ScreenEnum.EDIT]]);
    focusLimitRow(0);
  };

  const handleOnDelete = () => {
    writeAll([['__metadata.limitUuid', limitUuid], ['__metadata.screen', ScreenEnum.DELETE]]);
    focusConfirmQuestion();
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
        <Button aria-label={`More actions for budget ${label}`} data-limit-menu={limitUuid} onKeyDown={handleOnKeyDown} ref={buttonRef} type="text">
          <Lucide icon={EllipsisVertical} />
        </Button>
      </Dropdown>
    </Tooltip>
  );
}

export default BudgetMenu;
