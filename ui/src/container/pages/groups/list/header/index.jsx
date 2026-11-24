import Lucide from '@Components/lucide';
import { CollapsedTitle } from '@Container/layout';
import {
  GroupsTabEnum, TAB_QP, filterByTab, parseTab,
} from '@Container/pages/groups/list/helpers';
import useModals, { modals } from '@Hooks/use-modals';
import { useGetGroupsQuery } from '@State/groups/api';
import { Button, Helmet, NewHeader, SectionTitle, Tooltip } from '@radicalbit/radicalbit-design-system';
import { Layers, Plus } from 'lucide-react';
import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import Subtitle from './subtitle';

function GroupsListHeader() {
  const [searchParams] = useSearchParams();

  const { data = [], isError } = useGetGroupsQuery();

  const tab = parseTab(searchParams.get(TAB_QP));
  const isGatewayManagedTab = tab === GroupsTabEnum.GATEWAY_MANAGED;
  const count = filterByTab(data, GroupsTabEnum.GATEWAY_MANAGED).length;
  const hasCreateButton = isGatewayManagedTab && (count !== 0 || isError);

  useOpenModalWithKeyboard();

  return (
    <>
      <Helmet title="Groups – Radicalbit Platform" />

      <NewHeader
        details={{
          one: hasCreateButton && <CreateGroupButton />,
        }}
        title={(
          <SectionTitle
            level={1}
            subtitle={<Subtitle />}
            title="Groups"
            titlePrefix={<Lucide icon={Layers} />}
          />
        )}
      />
    </>
  );
}

function CreateGroupButton() {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.CREATE_GROUPS);
  };

  return (
    <TooltipCreateNewGroup>
      <Button icon={<Lucide icon={Plus} />} onClick={handleOnClick} type="primary">
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
