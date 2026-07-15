import useModals, { modals } from '@Hooks/use-modals';
import { useGetAlertsQuery } from '@State/alerts/api';
import { faPlus, faSliders } from '@fortawesome/free-solid-svg-icons';
import {
  Button,
  FontAwesomeIcon,
  NewHeader,
  SectionTitle,
} from '@radicalbit/radicalbit-design-system';

function AlertsListHeader() {
  const { data = [] } = useGetAlertsQuery();
  const count = data.length;

  return (
    <NewHeader
      details={{
        one: count !== 0 && <CreateAlertRuleButton />,
      }}
      title={(
        <SectionTitle
          title="Alert Notification"
          titlePrefix={<FontAwesomeIcon icon={faSliders} />}
        />
      )}
    />
  );
}

function CreateAlertRuleButton() {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.CREATE_ALERT_RULE);
  };

  return (
    <Button onClick={handleOnClick} prefix={<FontAwesomeIcon icon={faPlus} />} type="primary">
      Create Rule
    </Button>
  );
}

export default AlertsListHeader;
