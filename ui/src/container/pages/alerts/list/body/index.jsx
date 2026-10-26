import Lucide from '@Components/lucide';
import { DETAIL_LAYOUT_CONFIGURATION, MAIN_LAYOUT_CONFIGURATION } from '@Container/layout/layout-provider/layout-provider-configuration';
import { useGetAlertsHistoryQuery, useGetAlertsQuery, useDeleteAlertMutation } from '@State/alerts/api';
import { PathsEnum } from '@Src/constants';
import {
  Board, Button, DataTable, Spin, Void,
} from '@radicalbit/radicalbit-design-system';
import { TriangleAlert } from 'lucide-react';
import { useEffect, useMemo } from 'react';
import { useDispatch } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import columns from './columns';
import VerticalResizableDivider from './vertical-resizable-divider';

function AlertsList() {
  const navigate = useNavigate();
  const { uuid } = useParams();
  const {
    data = [], isLoading, isFetching, isError, isSuccess, refetch,
  } = useGetAlertsQuery();
  const { data: history } = useGetAlertsHistoryQuery();
  const rules = useMemo(() => withAlertTotals(data, history), [data, history]);

  useInitLayoutConfigurations();

  if (isLoading) {
    return <Spin spinning />;
  }

  if (isError) {
    return (
      <div className="flex justify-center h-full">
        <IsError isFetching={isFetching} refetch={refetch} />
      </div>
    );
  }

  if (!isSuccess) {
    return false;
  }

  const handleOnRowClick = (record) => {
    const { search } = window.location;
    navigate(`/${PathsEnum.ALERTS}/${record.uuid}${search}`);
  };

  const components = { body: { row: RowWithSpinner } };

  return (
    <>
      <DataTable
        clickable
        columns={columns}
        components={components}
        dataSource={rules}
        onRow={(record) => ({
          onClick: () => {
            handleOnRowClick(record);
          },
        })}
        pagination={{
          hideOnSinglePage: true,
        }}
        rowClassName={({ uuid: alertUuid }) => alertUuid === uuid ? DataTable.ROW_PRIMARY_LIGHT : undefined}
        rowKey={({ uuid: alertUuid }) => alertUuid}
        scroll={{ y: 'calc(100vh - 10rem)', x: '100vh' }}
      />

      <VerticalResizableDivider />
    </>
  );
}

const withAlertTotals = (rules, history) => {
  if (!history) {
    return rules;
  }

  const totals = {};
  history.forEach(({ ruleUuid, sent, failed }) => {
    const current = totals[ruleUuid] ?? { sent: 0, failed: 0 };
    totals[ruleUuid] = { sent: current.sent + sent, failed: current.failed + failed };
  });

  return rules.map((rule) => ({
    ...rule, sent: 0, failed: 0, ...totals[rule.uuid],
  }));
};

const useInitLayoutConfigurations = () => {
  const dispatch = useDispatch();
  const { uuid } = useParams();

  useEffect(() => {
    if (!uuid) {
      MAIN_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
    } else {
      DETAIL_LAYOUT_CONFIGURATION.forEach((action) => dispatch(action()));
    }
  }, [dispatch, uuid]);
};

function RowWithSpinner({ children, ...other }) {
  const [, { isLoading: isDeleting }] = useDeleteAlertMutation({ fixedCacheKey: `delete-alert-${other['data-row-key']}` });

  return isDeleting
    ? (
      <tr {...other}>
        {/* IF scroll={{ y: 'calc(100vh - 10rem)' }} is defined, colSpan must be === columns.length */}
        <td colSpan={columns.length}>
          <Spin spinning />
        </td>
      </tr>
    )
    : <tr {...other}>{children}</tr>;
}

function IsError({ refetch, isFetching }) {
  return (
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
          title="Unable to load alert rules"
        />
      )}
      width="100%"
    />
  );
}

export default AlertsList;
