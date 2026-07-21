import Lucide from '@Components/lucide';
import { CollapsedTitle } from '@Container/layout';
import useModals, { modals } from '@Hooks/use-modals';
import { useGetKeysQuery } from '@State/keys/api';
import {
  Button,
  NewHeader,
  SectionTitle,
  Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { Key, Plus } from 'lucide-react';
import { useEffect } from 'react';
import Subtitle from './subtitle';

function KeysListHeader() {
  const { data = [] } = useGetKeysQuery();
  const count = data.length;

  useOpenModalWithKeyboard();

  return (
    <NewHeader
      details={{
        one: count !== 0 && <CreateKeyButton />,
      }}
      title={(
        <SectionTitle
          subtitle={<Subtitle />}
          title="Credentials"
          titlePrefix={<Lucide icon={Key} />}
        />
      )}
    />
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
