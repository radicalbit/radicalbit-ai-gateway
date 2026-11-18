import Lucide from '@Components/lucide';
import useModals, { modals } from '@Hooks/use-modals';
import {
  Button,
  DataTableAction,
  Tooltip,
} from '@radicalbit/radicalbit-design-system';
import { ChartLine } from 'lucide-react';

function Analytics({ record }) {
  const { showModal } = useModals();

  const handleOnClick = (e) => {
    e.stopPropagation();
    showModal(modals.ROUTE_ANALYTICS, { routeName: record.routeName });
  };

  return (
    <DataTableAction noHide>
      <Tooltip title="Open route analytics">
        <Button aria-label="Open route analytics" onClick={handleOnClick} type="text">
          <Lucide icon={ChartLine} />
        </Button>
      </Tooltip>
    </DataTableAction>
  );
}

export default Analytics;
