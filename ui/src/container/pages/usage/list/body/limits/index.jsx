import Lucide from '@Components/lucide';
import { useGetLimitsStreamWithRange } from '@State/usage/vertical-hooks';
import {
  Board, Button, DataTable, FormField, Void,
} from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import ProjectFilter from '../project-filter';
import RoutesFilter from '../routes-filter';
import columns from './columns';
import LimitStatusFilter from './limit-status-filter';

function Limits() {
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

        <FormField label="Limit status">
          <LimitStatusFilter />
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
  const windowStatuses = searchParams.get('windowStatuses')
    ? searchParams.get('windowStatuses').split(',')
    : [];

  const { data, isLoading, isError, isFetching, refetch } = useGetLimitsStreamWithRange({ routes, windowStatuses });
  const dataSource = data || [];

  if (isError) {
    return <IsError isFetching={isFetching} refetch={refetch} />;
  }

  return (
    <DataTable
      columns={columns}
      dataSource={dataSource}
      loading={isLoading}
      pagination={false}
      rowKey={({ routeName: key }) => key}
    />
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

export default Limits;
