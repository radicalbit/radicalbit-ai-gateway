import Lucide from '@Components/lucide';
import TagsFilter from '@Components/tags-filter';
import TimeFilter from '@Components/time-filter';
import { useGetCostsSummaryStreamWithRange } from '@State/usage/vertical-hooks';
import {
  Board, Button, FormField, Skeleton, Void,
} from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
import { useId } from 'react';
import { useSearchParams } from 'react-router-dom';
import CostsGraph from './costs-graph';
import CostTable from './cost-table';
import InvocationsGraph from './invocations-graph';
import McpInvocationsGraph from './mcp-invocations-graph';
import McpKeysTable from './mcp-keys-table';
import ProjectFilter from '../project-filter';
import RoutesFilter from '../routes-filter';
import SummaryHeader from './summary-header';
import TokensGraph from './tokens-graph';

function Consumptions() {
  const projectId = useId();
  const routesId = useId();
  const tagsId = useId();
  const timeRangeId = useId();

  return (
    <div className="flex flex-col gap-4 h-full p-4">
      <div className="flex flex-row items-center gap-4">
        <FormField htmlFor={projectId} label="Project">
          <ProjectFilter id={projectId} />
        </FormField>

        <FormField htmlFor={tagsId} label="Tags">
          <TagsFilter id={tagsId} />
        </FormField>

        <FormField htmlFor={routesId} label="Routes">
          <RoutesFilter id={routesId} />
        </FormField>

        <FormField htmlFor={timeRangeId} label="Time range">
          <TimeFilter id={timeRangeId} reverse />
        </FormField>
      </div>

      <DataContent />

      <McpInvocationsGraph />

      <McpKeysTable />
    </div>
  );
}

function DataContent() {
  const [searchParams] = useSearchParams();
  const routes = searchParams.get('routes')
    ? searchParams.get('routes').split(',')
    : [];

  const { data, isFetching, refetch } = useGetCostsSummaryStreamWithRange({ routes, withSavedTokens: false });
  const isSseLoading = data?.isSseLoading;
  const isSseError = data?.isSseError;
  const isSseSuccess = data?.isSseSuccess;

  if (isSseLoading) {
    return <Skeleton.Node active style={{ height: '20rem', width: '100%' }} />;
  }

  if (isSseError) {
    return <IsError isFetching={isFetching} refetch={refetch} />;
  }

  if (!isSseSuccess) {
    return false;
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
    <div className="flex justify-center">
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

export default Consumptions;
