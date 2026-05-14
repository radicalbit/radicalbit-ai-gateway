import { faTrash } from '@fortawesome/free-solid-svg-icons';
import TimeFilter from '@Components/time-filter';
import useModals from '@Hooks/use-modals';
import {
  FontAwesomeIcon, NewHeader, RbitModal,
  SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import InvocationsGraph from './invocations-graph';
import RequestsGraph from './requests-graph';
import RouteDetailTable from './route-detail-table';
import TokensGraph from './tokens-graph';

function RouteAnalytics() {
  const { hideModal, modalPayload } = useModals();
  const routeName = modalPayload?.data?.routeName;

  return (
    <RbitModal
      closable={false}
      defaultMaximize
      header={(
        <NewHeader
          details={{
            one: <TimeFilter />,
            two: <FontAwesomeIcon icon={faTrash} onClick={hideModal} />,
          }}
          title={<SectionTitle subtitle={routeName} title="Drill-down" />}
        />
      )}
      onCancel={hideModal}
      open
    >
      <div className="flex flex-col gap-4">
        <RouteDetailTable routeName={routeName} />

        <InvocationsGraph routeName={routeName} />

        <div className="flex flex-row gap-4 [&>*]:flex-1">
          <TokensGraph routeName={routeName} />

          <RequestsGraph routeName={routeName} />
        </div>
      </div>
    </RbitModal>
  );
}

export default RouteAnalytics;
