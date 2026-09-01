import Lucide from '@Components/lucide';
import TagsFilter from '@Components/tags-filter';
import TimeFilter from '@Components/time-filter';
import { WIDE_MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import { useGetCostsSummaryStreamWithRange } from '@State/usage/vertical-hooks';
import {
  Board, Button, FormField, Skeleton, Void,
} from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
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

        <FormField label="Tags">
          <TagsFilter />
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
    return <IsError isFetching={isFetching} refetch={refetch} />;
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

function IsError({ isFetching, refetch }) {
  return (
    <div className="flex justify-center h-full">
      <Board
        main={(
          <Void
            actions={<Button loading={isFetching} onClick={refetch}>Retry</Button>}
            description={(
              <>
                This might be temporary
                <br />
                please retry later
              </>
            )}
            image={<Lucide icon={TriangleAlert} />}
            title="Unable to load usage data"
          />
        )}
        width="100%"
      />
    </div>
  );
}

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();

  useEffect(() => {
    WIDE_MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
  }, [dispatch]);
};

export default Consumptions;
