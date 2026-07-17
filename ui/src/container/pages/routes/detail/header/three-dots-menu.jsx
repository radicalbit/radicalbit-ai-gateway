import Lucide from '@Components/lucide';
import useModals, { modals } from '@Hooks/use-modals';
import { Button, Dropdown } from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical } from 'lucide-react';
import { useParams } from 'react-router-dom';

function ThreeDotsMenu() {
  const { name } = useParams();
  const items = useGetThreeDotsMenuItems(name);

  return (
    <Dropdown menu={{ items }}>
      <Button type="text">
        <Lucide icon={EllipsisVertical} />
      </Button>
    </Dropdown>

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
