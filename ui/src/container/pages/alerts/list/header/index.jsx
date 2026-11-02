import Lucide from '@Components/lucide';
import useModals, { modals } from '@Hooks/use-modals';
import { useGetAlertsQuery } from '@State/alerts/api';
import { Button, Helmet, NewHeader, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { Plus, SlidersHorizontal } from 'lucide-react';

function AlertsListHeader() {
  useGetAlertsQuery();

  return (
    <>
      <Helmet title="Alert Notification – Radicalbit Platform" />

      <NewHeader
        details={{
          one: <CreateAlertRuleButton />,
        }}
        title={(
          <SectionTitle
            level={1}
            title="Alert Notification"
            titlePrefix={<Lucide icon={SlidersHorizontal} />}
          />
        )}
      />
    </>
  );
}

function CreateAlertRuleButton() {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.CREATE_ALERT_RULE);
  };

  return (
    <Button onClick={handleOnClick} prefix={<Lucide icon={Plus} />} type="primary">
      Create Rule
    </Button>
  );
}

export default AlertsListHeader;
