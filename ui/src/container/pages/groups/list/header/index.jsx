import { CollapsedTitle } from '@Container/layout';
import useModals, { modals } from '@Hooks/use-modals';
import { useGetGroupsQuery } from '@State/groups/api';
import { faPlus, faLayerGroup } from '@fortawesome/free-solid-svg-icons';
import {
  Button, FontAwesomeIcon, NewHeader,
  SectionTitle,
  Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { useEffect } from 'react';
import Subtitle from './subtitle';

function GroupsListHeader() {
  const { data = [] } = useGetGroupsQuery();
  const count = data.length;

  useOpenModalWithKeyboard();

  return (
    <NewHeader
      details={{
        one: count !== 0 && <CreateGroupButton />,
      }}
      title={(
        <SectionTitle
          subtitle={<Subtitle />}
          title="Groups"
          titlePrefix={<FontAwesomeIcon icon={faLayerGroup} />}
        />
      )}
    />
  );
}

function CreateGroupButton() {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.CREATE_GROUPS);
  };

  return (
    <TooltipCreateNewGroup>
      <Button icon={<FontAwesomeIcon icon={faPlus} />} onClick={handleOnClick} type="primary">
        Create group
      </Button>
    </TooltipCreateNewGroup>
  );
}

function TooltipCreateNewGroup({ children }) {
  return (
    <Tooltip title={(<CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: 'N', shape: 'circle' }] }} />)}>
      {children}
    </Tooltip>
  );
}

const useOpenModalWithKeyboard = () => {
  const { showModal } = useModals();

  useEffect(() => {
    const handleKeyDown = (e) => {
      const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;

      if ((isMac && e.ctrlKey && e.code === 'KeyN')) {
        e.preventDefault();
        showModal(modals.CREATE_GROUPS);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [showModal]);
};

export default GroupsListHeader;
