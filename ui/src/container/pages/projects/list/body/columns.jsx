import Lucide from '@Components/lucide';
import ConfigStatusTag from '@Container/pages/projects/components/config-status-tag';
import ProjectStatusTag from '@Container/pages/projects/components/project-status-tag';
import { useGetThreeDotsMenuItems } from '@Container/pages/projects/list/body/three-dots-menu';
import useGetVisibleConfig from '@Container/pages/projects/use-get-visible-config';
import { DATE_FORMAT, DATE_FORMAT_SHORT } from '@Src/constants';
import {
  Button,
  DataTableAction,
  Dropdown,
  RelativeDateTime,
  SectionTitle,
  Truncate,
} from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical } from 'lucide-react';

const getColumns = () => [
  {
    title: '',
    dataIndex: 'margin-left',
    key: 'margin-left',
    width: '10px',
  },

  {
    title: 'Projects',
    dataIndex: 'name',
    key: 'name',
    render: (value, { description }) => (
      <SectionTitle
        size="small"
        subtitle={(
          <Truncate tooltip={{ title: description, placement: 'topLeft' }}>
            {description || '--'}
          </Truncate>
          )}
        title={(
          <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
            {value}
          </Truncate>
        )}
      />
    ),
  },

  {
    title: 'Deploy Status',
    dataIndex: 'projectStatus',
    key: 'projectStatus',
    render: (value) => <ProjectStatusTag projectStatus={value} />,
  },

  {
    title: 'Last Edit',
    dataIndex: 'updatedAt',
    key: 'updatedAt',
    align: 'left',
    render: (date) => <RelativeDateTime format={DATE_FORMAT_SHORT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },

  {
    title: 'Configurations',
    dataIndex: 'configs',
    key: 'configs',
    render: (configs) => <ConfigurationCell configs={configs} />,
  },

  {
    title: '',
    dataIndex: 'uuid',
    key: 'actions',
    width: '30px',
    render: (uuid) => (
      <DataTableAction noHide>
        <Actions uuid={uuid} />
      </DataTableAction>
    ),
  },

  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },
];

function ConfigurationCell({ configs }) {
  const config = useGetVisibleConfig(configs);

  if (!config) {
    return '--';
  }

  return (
    <div className="flex items-center gap-4">
      <span>{`Slot ${config.slot}`}</span>

      <ConfigStatusTag config={config} />
    </div>
  );
}

function Actions({ uuid }) {
  const items = useGetThreeDotsMenuItems(uuid);

  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  if (!items.length) {
    return false;
  }

  return (
    <Dropdown className="c-project-config-menu" menu={{ items }}>
      <Button onClick={handleOnClick} type="text">
        <Lucide icon={EllipsisVertical} />
      </Button>
    </Dropdown>
  );
}

export default getColumns;
