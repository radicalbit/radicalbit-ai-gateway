import { useGetLimitsStreamWithRange } from '@State/usage/vertical-hooks';
import { faWarning } from '@fortawesome/free-solid-svg-icons';
import {
  Board, Button, DataTable, FontAwesomeIcon, FormField, Void,
} from '@radicalbit/radicalbit-design-system';
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

  const { data, isLoading, isError, refetch } = useGetLimitsStreamWithRange({ routes, windowStatuses });
  const dataSource = data || [];

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

export default Limits;
