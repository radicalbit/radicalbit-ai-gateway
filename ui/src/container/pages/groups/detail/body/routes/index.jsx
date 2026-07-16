import Lucide from '@Components/lucide';
import { ROUTE_DETAIL_TABS } from '@Container/pages/routes/detail/body';
import useModals, { modals } from '@Hooks/use-modals';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import { useGetGroupQuery } from '@State/groups/api';
import {
  Button, Collapse, DataTable,
} from '@radicalbit/radicalbit-design-system';
import { Plus } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import columns from './columns';

function Routes() {
  const { uuid } = useParams();
  const { data } = useGetGroupQuery(uuid);
  const routes = data?.routes || [];
  const count = routes.length;

  return (
    <Collapse
      key={`route-${uuid}-${count}`} // needed to re-render the collapse
      defaultActiveKey={['1']}
      items={[
        {
          key: '1',
          label: <LabelRoute />,
          children: <ChildrenRoute />,
        },
      ]}
      type="no-border"
    />
  );
}
function LabelRoute() {
  const { showModal } = useModals();

  const { uuid } = useParams();
  const { data } = useGetGroupQuery(uuid);
  const routes = data?.routes || [];
  const count = routes.length;

  const handleOnClick = (e) => {
    e.stopPropagation();
    showModal(modals.ADD_ROUTES_TO_GROUP, { uuid });
  };

  if (count === 1) {
    return (
      <div className="flex justify-between items-center">
        <strong>{`${count} Associated route`}</strong>

        <Button icon={<Lucide icon={Plus} />} onClick={handleOnClick}>Associate routes</Button>
      </div>
    );
  }

  return (
    <div className="flex justify-between items-center">
      <strong>{`${count} Associated routes`}</strong>

      <Button icon={<Lucide icon={Plus} />} onClick={handleOnClick}>Associate routes</Button>
    </div>
  );
}

function ChildrenRoute() {
  const navigate = useNavigate();
  const { uuid } = useParams();
  const { data, isLoading } = useGetGroupQuery(uuid);
  const routes = data?.routes || [];

  const handleOnRowClick = (record) => {
    navigate(`/${PathsEnum.ROUTES}/${record.name}?tab=${ROUTE_DETAIL_TABS.associations.key}&${SEARCH_PARAMS.routes}=${encodeURIComponent(record.name)}&projectUuid=${record.projectUuid}`);
  };

  return (
    <DataTable
      clickable
      columns={columns}
      dataSource={routes}
      loading={isLoading}
      onRow={(record) => ({
        onClick: () => {
          handleOnRowClick(record);
        },
      })}
      pagination={{
        hideOnSinglePage: true,
      }}
      rowKey={({ uuid: routeUUID }) => routeUUID}
      size="small"
    />
  );
}

export default Routes;
