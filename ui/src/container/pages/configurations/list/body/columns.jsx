import TableRowButton from '@Components/table-row-button';
import ConfigStatusTag from '@Container/pages/projects/components/config-status-tag';
import useModals, { modals } from '@Hooks/use-modals';
import { DATE_FORMAT, DATE_FORMAT_SHORT } from '@Src/constants';
import {
  DataTableAction,
  RelativeDateTime,
  SectionTitle,
  Truncate,
} from '@radicalbit/radicalbit-design-system';
import SlotActions from './slot-actions';

function EditConfiguration({ children, uuid }) {
  const { showModal } = useModals();

  const handleOnClick = () => {
    showModal(modals.EDIT_PROJECT_CONFIG, { uuid });
  };

  return <TableRowButton onClick={handleOnClick}>{children}</TableRowButton>;
}

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
    render: (value, { description, uuid }) => (
      <SectionTitle
        size="small"
        subtitle={(
          <Truncate tooltip={{ title: description, placement: 'topLeft' }}>
            {description || '--'}
          </Truncate>
        )}
        title={(
          <Truncate tooltip={{ title: value, placement: 'topLeft' }}>
            <EditConfiguration uuid={uuid}>{value}</EditConfiguration>
          </Truncate>
        )}
      />
    ),
  },

  {
    title: 'Last Update',
    dataIndex: 'updatedAt',
    key: 'updatedAt',
    align: 'left',
    render: (date) => <RelativeDateTime format={DATE_FORMAT_SHORT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },

  {
    title: 'Created',
    dataIndex: 'createdAt',
    key: 'createdAt',
    align: 'left',
    render: (date) => <RelativeDateTime format={DATE_FORMAT_SHORT} formatTooltip={DATE_FORMAT} timestamp={date} withTooltip />,
  },

  {
    title: 'Configurations',
    dataIndex: 'configs',
    key: 'configs',
    render: (configs = []) => (
      <div className="flex flex-col gap-2">
        {configs.map((config) => (
          <div key={config.uuid} className="flex items-center gap-4 h-8">
            <span>{`Slot ${config.slot}`}</span>

            <ConfigStatusTag config={config} />
          </div>
        ))}
      </div>
    ),
  },

  {
    title: '',
    dataIndex: 'configs',
    key: 'actions',
    width: '80px',
    render: (configs, { uuid, name }) => (
      <DataTableAction noHide>
        <div className="flex flex-col gap-2">
          {(configs ?? []).map((config) => (
            <div key={config.uuid} className="flex items-center justify-end h-8">
              <SlotActions config={config} projectName={name} projectUuid={uuid} />
            </div>
          ))}
        </div>
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

export default getColumns;
