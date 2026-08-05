import Lucide from '@Components/lucide';
import useModals, { modals } from '@Hooks/use-modals';
import {
  DataTableAction,
  Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { ChartLine } from 'lucide-react';

function Analytics({ record }) {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.ROUTE_ANALYTICS, { routeName: record.routeName });
  };

  return (
    <DataTableAction noHide>
      <Tooltip title="Open route analytics">
        <Lucide icon={ChartLine} onClick={handleOnClick} />
      </Tooltip>
    </DataTableAction>
  );
}

export default Analytics;
