import Lucide from '@Components/lucide';
import { useGetRequestsWithRange } from '@State/requests/vertical-hooks';
import {
  Board, DataTable, NewHeader, SectionTitle,
} from '@radicalbit/radicalbit-design-system';
import { useSearchParams } from 'react-router-dom';
import { REQUESTS_PAGE_PARAM, SELECTED_REQUEST_PARAM } from './constants';
import { selectedRequestUuid } from './helpers';
import { ICONS } from './request-icons';
import RequestRow from './request-row';

const COLUMNS = [
  {
    key: 'request',
    render: (_, request) => <RequestRow request={request} />,
  },
];

const HEADER_PROPS = { divider: true, padding: 'compact' };

const MAIN_PROPS = { divider: true, padding: 'compact', type: 'secondary' };

const SECONDARY_PROPS = { padding: 'none' };

function RequestsList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Number(searchParams.get(REQUESTS_PAGE_PARAM)) || 1;
  const requestUuid = searchParams.get(SELECTED_REQUEST_PARAM);

  const { data } = useGetRequestsWithRange({ page });
  const items = data?.items ?? [];
  const total = data?.total;
  const size = data?.size;

  const selectedUuid = selectedRequestUuid(items, requestUuid);
  const totalLabel = total === 1 ? '1 request' : `${total} requests`;

  const handleOnTableChange = (pagination) => {
    setSearchParams((prev) => {
      prev.set(REQUESTS_PAGE_PARAM, pagination.current);
      prev.delete(SELECTED_REQUEST_PARAM);
      return prev;
    });
  };

  const handleOnRow = (request) => ({
    onClick: () => {
      setSearchParams((prev) => {
        prev.set(SELECTED_REQUEST_PARAM, request.requestUuid);
        return prev;
      });
    },
  });

  const handleOnRowClassName = (request) => {
    if (request.requestUuid === selectedUuid) {
      return DataTable.ROW_PRIMARY_LIGHT;
    }

    return '';
  };

  return (
    <Board
      header={(
        <NewHeader
          details={{ one: <div className="text-xs">{totalLabel}</div> }}
          padding="none"
          title={<SectionTitle title="Requests" />}
        />
      )}
      headerProps={HEADER_PROPS}
      main={<Legend />}
      mainProps={MAIN_PROPS}
      secondary={(
        <DataTable
          clickable
          columns={COLUMNS}
          dataSource={items}
          noHead
          noPadding
          onChange={handleOnTableChange}
          onRow={handleOnRow}
          pagination={{
            current: page,
            pageSize: size,
            showSizeChanger: false,
            total,
          }}
          rowClassName={handleOnRowClassName}
          rowKey="requestUuid"
          size="small"
        />
      )}
      secondaryProps={SECONDARY_PROPS}
      width="100%"
    />
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <strong>Triggered on the request</strong>

      {Object.entries(ICONS).map(([kind, { icon, label }]) => (
        <span key={kind} className="inline-flex items-center gap-1">
          <Lucide icon={icon} />

          {label}
        </span>
      ))}
    </div>
  );
}

export default RequestsList;
