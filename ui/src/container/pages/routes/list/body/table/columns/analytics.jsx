import useModals, { modals } from '@Hooks/use-modals';
import { faChartLine } from '@fortawesome/free-solid-svg-icons';
import {
  DataTableAction, FontAwesomeIcon,
  Tooltip,
} from '@radicalbit/radicalbit-design-system';

function Analytics({ record }) {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.ROUTE_ANALYTICS, { routeName: record.routeName });
  };

  return (
    <DataTableAction>
      <Tooltip title="Open route analytics">
        <FontAwesomeIcon className="p-4" icon={faChartLine} onClick={handleOnClick} />
      </Tooltip>
    </DataTableAction>
  );
}

export default Analytics;
