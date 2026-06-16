import SomethingWentWrong from '@Components/error-page/something-went-wrong';
import { CreateProjectButton } from '@Container/pages/projects/list/header';
import { SEARCH_PARAMS } from '@Src/constants';
import {
  useApproveConfigMutation,
  useCancelApprovalMutation,
  useDeleteProjectMutation,
  useGetProjectsQuery,
  useServeConfigMutation,
  useUnserveConfigMutation,
} from '@State/projects/api';
import { faCircleXmark } from '@fortawesome/free-solid-svg-icons';
import {
  Board,
  DataTable,
  FontAwesomeIcon,
  Search,
  Spin,
  Void,
} from '@radicalbit/radicalbit-design-system';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import getColumns from './columns';

function ProjectsList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const searchValue = searchParams.get(SEARCH_PARAMS.projects) || '';

  const handleSearchChange = (e) => {
    const { value } = e.target;
    setSearchParams((prev) => {
      if (value) {
        prev.set(SEARCH_PARAMS.projects, value);
      } else {
        prev.delete(SEARCH_PARAMS.projects);
      }
      return prev;
    });
  };

  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="flex flex-row items-center gap-4 pl-4 pt-4">
        <Search
          allowClear={{ clearIcon: <FontAwesomeIcon icon={faCircleXmark} /> }}
          onChange={handleSearchChange}
          placeholder="Search projects by name"
          style={{ width: '300px' }}
          value={searchValue}
        />

        <ProjectsCount searchValue={searchValue} />
      </div>

      <ProjectsTable searchValue={searchValue} />
    </div>
  );
}

function ProjectsCount({ searchValue }) {
  const { data = [], isSuccess } = useGetProjectsQuery();
  const filteredData = searchValue
    ? data.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()))
    : data;
  const count = filteredData.length;

  if (!isSuccess) {
    return false;
  }

  if (count === 1) {
    return (
      <div className="flex items-center">
        {`${count} Project`}
      </div>
    );
  }

  return (
    <div className="flex items-center">
      {`${count} Projects`}
    </div>
  );
}

function ProjectsTable({ searchValue }) {
  const { data = [], isError, isLoading, isSuccess } = useGetProjectsQuery();

  if (isLoading) {
    return <DataTable loading />;
  }

  if (isError) {
    return (
      <Board
        main={<SomethingWentWrong size="small" />}
      />
    );
  }

  if (!data?.length) {
    return (
      <Board
        borderType="none"
        main={(
          <Void
            description="No projects found."
            title="Projects"
          />
        )}
        suffix={<CreateProjectButton />}
      />
    );
  }

  if (!isSuccess) {
    return false;
  }

  return <IsSuccess searchValue={searchValue} />;
}

function IsSuccess({ searchValue }) {
  const { data = [] } = useGetProjectsQuery();

  const filteredData = searchValue
    ? data.filter(({ name }) => name.toLowerCase().includes(searchValue.toLowerCase()))
    : data;

  const sortedData = useMemo(
    () => [...filteredData].sort((a, b) => (b.createdAt ?? '').localeCompare(a.createdAt ?? '')),
    [filteredData],
  );

  const columns = getColumns();

  const components = useMemo(() => ({ body: { row: makeRowWithSpinner(columns.length) } }), [columns.length]);

  return (
    <DataTable
      columns={columns}
      components={components}
      dataSource={sortedData}
      pagination={{ hideOnSinglePage: true }}
      rowKey={({ uuid: projectUUID }) => projectUUID}
      scroll={{ y: 'calc(100vh - 10rem)' }}
    />
  );
}

const makeRowWithSpinner = (colSpan) => function RowWithSpinner({ children, ...other }) {
  const rowKey = other['data-row-key'];

  const { data = [] } = useGetProjectsQuery();
  const project = data.find(({ uuid }) => uuid === rowKey);
  const configs = project?.configs ?? [];
  const configAUuid = configs[0]?.uuid;
  const configBUuid = configs[1]?.uuid;

  const isConfigABusy = useIsConfigBusy(configAUuid);
  const isConfigBBusy = useIsConfigBusy(configBUuid);

  const [, { isLoading: isDeleting }] = useDeleteProjectMutation({ fixedCacheKey: `delete-project-${rowKey}` });

  const isBusy = isConfigABusy || isConfigBBusy || isDeleting;

  if (isBusy) {
    return (
      <tr {...other}>
        <td colSpan={colSpan}>
          <Spin spinning />
        </td>
      </tr>
    );
  }

  return <tr {...other}>{children}</tr>;
};

const useIsConfigBusy = (configUuid) => {
  const [, { isLoading: isApproving }] = useApproveConfigMutation({ fixedCacheKey: `approve-config-${configUuid}` });
  const [, { isLoading: isCancelling }] = useCancelApprovalMutation({ fixedCacheKey: `cancel-approval-${configUuid}` });
  const [, { isLoading: isServing }] = useServeConfigMutation({ fixedCacheKey: `serve-config-${configUuid}` });
  const [, { isLoading: isUnserving }] = useUnserveConfigMutation({ fixedCacheKey: `unserve-config-${configUuid}` });

  return isApproving || isCancelling || isServing || isUnserving;
};

export default ProjectsList;
