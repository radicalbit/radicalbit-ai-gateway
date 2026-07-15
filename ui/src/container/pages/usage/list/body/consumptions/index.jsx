import TimeFilter from '@Components/time-filter';
import { WIDE_MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import { useGetCostsSummaryStreamWithRange } from '@State/usage/vertical-hooks';
import { faWarning } from '@fortawesome/free-solid-svg-icons';
import {
  Board, Button, FontAwesomeIcon, FormField, Skeleton, Void,
} from '@radicalbit/radicalbit-design-system';
import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import CostsGraph from './costs-graph';
import CostTable from './cost-table';
import InvocationsGraph from './invocations-graph';
import ProjectFilter from '../project-filter';
import RoutesFilter from '../routes-filter';
import SummaryHeader from './summary-header';
import TokensGraph from './tokens-graph';

function Consumptions() {
  useInitLayoutConfigurations();

  const [searchParams] = useSearchParams();
  const projectUuid = searchParams.get('projectUuid');

  if (!projectUuid) {
    return (
      <div className="flex flex-col gap-4 h-full p-4">
        <div className="flex flex-row items-center gap-4">
          <FormField label="Project">
            <ProjectFilter />
          </FormField>
        </div>

        <Void description="Select a project to view usage data" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 h-full p-4">
      <div className="flex flex-row items-center gap-4">
        <FormField label="Project">
          <ProjectFilter />
        </FormField>

        <FormField label="Routes">
          <RoutesFilter />
        </FormField>

        <FormField label="Time range">
          <TimeFilter reverse />
        </FormField>
      </div>

      <DataContent />
    </div>
  );
}

function DataContent() {
  const [searchParams] = useSearchParams();
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const { isError, isFetching, isSuccess, refetch } = useGetCostsSummaryStreamWithRange({ routes, withSavedTokens: false });

  if (isFetching) {
    return <Skeleton.Node active style={{ height: '20rem', width: '100%' }} />;
  }

  if (isError) {
    return (
      <div className="flex justify-center h-full">
        <Board
          main={(
            <Void
              actions={<Button onClick={refetch}>Retry</Button>}
              description={(
                <>
                  This might be temporary
                  <br />
                  please retry later
                </>
              )}
              image={<FontAwesomeIcon icon={faWarning} />}
              title="Unable to load usage data"
            />
          )}
          width="100%"
        />
      </div>
    );
  }

  if (!isSuccess) {
    return null;
  }

  return (
    <>
      <Board
        header={<SummaryHeader />}
        main={<CostTable />}
      />

      <CostsGraph />

      <div className="flex flex-row gap-4">
        <div className="flex-1">
          <TokensGraph />
        </div>

        <div className="flex-1">
          <InvocationsGraph />
        </div>
      </div>
    </>
  );
}

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();

  useEffect(() => {
    WIDE_MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
  }, [dispatch]);
};

export default Consumptions;
