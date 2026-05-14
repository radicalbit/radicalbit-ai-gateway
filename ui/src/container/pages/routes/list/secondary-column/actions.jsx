import useModals, { modals } from '@Hooks/use-modals';
import { faPlus } from '@fortawesome/free-solid-svg-icons';
import { Button, FontAwesomeIcon } from '@radicalbit/radicalbit-design-system';

function Actions() {
  const { showModal } = useModals();

  const handleOnCreateNewSecretKey = () => {
    showModal(modals.CREATE_KEY);
  };

  const handleOnCreateNewGroup = () => {
    showModal(modals.CREATE_GROUPS);
  };

  return (
    <div className="flex flex-col gap-2">
      <Button onClick={handleOnCreateNewSecretKey} prefix={<FontAwesomeIcon icon={faPlus} />} type="primary">
        Create credential
      </Button>

      <Button icon={<FontAwesomeIcon icon={faPlus} />} onClick={handleOnCreateNewGroup} type="primary">
        Create group
      </Button>
    </div>
  );
}

export default Actions;
