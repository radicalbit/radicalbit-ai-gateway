import Lucide from '@Components/lucide';
import { CollapsedTitle } from '@Container/layout';
import {
  OwnershipTabEnum, TAB_QP, filterByTab, parseTab,
} from '@Helpers/ownership-tabs';
import useModals, { modals } from '@Hooks/use-modals';
import { useGetKeysQuery } from '@State/keys/api';
import { Button, Helmet, NewHeader, SectionTitle, Tooltip } from '@radicalbit/radicalbit-design-system';
import { Key, Plus } from 'lucide-react';
import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import Subtitle from './subtitle';

function KeysListHeader() {
  const [searchParams] = useSearchParams();

  const { data = [], isError } = useGetKeysQuery();

  const tab = parseTab(searchParams.get(TAB_QP));
  const isGatewayManagedTab = tab === OwnershipTabEnum.GATEWAY_MANAGED;
  const count = filterByTab(data, OwnershipTabEnum.GATEWAY_MANAGED).length;
  const hasCreateButton = isGatewayManagedTab && (count !== 0 || isError);

  useOpenModalWithKeyboard();

  return (
    <>
      <Helmet title="Credentials – Radicalbit Platform" />

      <NewHeader
        details={{
          one: hasCreateButton && <CreateKeyButton />,
        }}
        title={(
          <SectionTitle
            level={1}
            subtitle={<Subtitle />}
            title="Credentials"
            titlePrefix={<Lucide icon={Key} />}
          />
        )}
      />
    </>
  );
}

function CreateKeyButton() {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.CREATE_KEY);
  };

  return (
    <TooltipCreateNewKey>
      <Button onClick={handleOnClick} prefix={<Lucide icon={Plus} />} type="primary">
        Create credential
      </Button>
    </TooltipCreateNewKey>
  );
}

function TooltipCreateNewKey({ children }) {
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
        showModal(modals.CREATE_KEY);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [showModal]);
};

export default KeysListHeader;
