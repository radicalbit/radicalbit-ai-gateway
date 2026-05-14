import useModals, { modals } from '@Hooks/use-modals';
import { faEllipsisVertical } from '@fortawesome/free-solid-svg-icons';
import { Button, Dropdown, FontAwesomeIcon } from '@radicalbit/radicalbit-design-system';
import { useParams } from 'react-router-dom';

function ThreeDotsMenu() {
  const { name } = useParams();
  const items = useGetThreeDotsMenuItems(name);

  return (
    <Dropdown menu={{ items }}>
      <Button type="text">
        <FontAwesomeIcon icon={faEllipsisVertical} />
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
