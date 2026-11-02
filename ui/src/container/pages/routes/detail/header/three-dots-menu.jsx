import Lucide from '@Components/lucide';
import useModals, { modals } from '@Hooks/use-modals';
import { Button, Dropdown, Tooltip } from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical } from 'lucide-react';
import { useParams } from 'react-router-dom';
import { useRef, useState } from 'react';

const MENU_TRIGGER = ['hover', 'click'];

function ThreeDotsMenu() {
  const buttonRef = useRef(null);

  const [isOpenedByKeyboard, setIsOpenedByKeyboard] = useState(false);

  const { name } = useParams();
  const items = useGetThreeDotsMenuItems(name);

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
        <Button aria-label="More actions" onKeyDown={handleOnKeyDown} ref={buttonRef} type="text">
          <Lucide icon={EllipsisVertical} />
        </Button>
      </Dropdown>
    </Tooltip>

  );
}

export const useGetThreeDotsMenuItems = (name) => {
  const { showModal } = useModals();

  const handleOnAssociate = () => {
    showModal(modals.ADD_GROUPS_TO_ROUTE, { name });
  };

  return [
    {
      label: 'Associate groups',
      onClick: handleOnAssociate,
    },
  ];
};

export default ThreeDotsMenu;
