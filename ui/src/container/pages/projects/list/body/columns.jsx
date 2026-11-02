import LimitsSummary from '@Components/limits/limits-summary';
import Lucide from '@Components/lucide';
import ConfigStatusTag from '@Container/pages/projects/components/config-status-tag';
import ProjectStatusTag from '@Container/pages/projects/components/project-status-tag';
import { useGetThreeDotsMenuItems } from '@Container/pages/projects/list/body/three-dots-menu';
import useGetVisibleConfig from '@Container/pages/projects/use-get-visible-config';
import useModals, { modals } from '@Hooks/use-modals';
import { DATE_FORMAT, DATE_FORMAT_SHORT } from '@Src/constants';
import {
  Button,
  DataTableAction,
  Dropdown,
  RelativeDateTime,
  SectionTitle,
  Tooltip,
  Truncate,
} from '@radicalbit/radicalbit-design-system';
import { EllipsisVertical } from 'lucide-react';
import { useRef, useState } from 'react';

const MENU_TRIGGER = ['hover', 'click'];

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
    title: 'Budget',
    dataIndex: 'limits',
    key: 'budget',
    render: (limits, { routeBudgets, uuid }) => <BudgetCell limits={limits} routeBudgets={routeBudgets} uuid={uuid} />,
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
    render: (uuid, { name }) => (
      <DataTableAction noHide>
        <Actions name={name} uuid={uuid} />
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

function BudgetCell({ limits, routeBudgets, uuid }) {
  const { showModal } = useModals();

  const routes = routeBudgets?.published ?? [];

  const handleOnManage = () => {
    showModal(modals.MANAGE_PROJECT_BUDGET, { uuid });
  };

  if (!limits?.length && routes.length) {
    const tooltip = `Budget set on routes: ${routes.join(', ')}`;

    return (
      <Tooltip title={tooltip}>
        <span className="opacity-70">Per route</span>
      </Tooltip>
    );
  }

  return <LimitsSummary limits={limits} noun="budget" onManage={handleOnManage} withCategory={false} />;
}

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

function Actions({ name, uuid }) {
  const buttonRef = useRef(null);

  const [isOpenedByKeyboard, setIsOpenedByKeyboard] = useState(false);

  const items = useGetThreeDotsMenuItems(uuid);

  const handleOnOpenChange = (isOpen) => {
    const { activeElement } = document;
    const isFocusLost = activeElement === document.body || activeElement?.closest('.ant-dropdown');

    if (!isOpen) {
      setIsOpenedByKeyboard(false);
    }

    if (!isOpen && isFocusLost) {
      buttonRef.current?.focus();
    }
  };

  const handleOnKeyDown = (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      setIsOpenedByKeyboard(true);
    }
  };

  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  if (!items.length) {
    return false;
  }

  return (
    <span onClick={handleOnClick} role="presentation">
      <Tooltip title="More actions">
        <Dropdown autoFocus={isOpenedByKeyboard} className="c-project-config-menu" destroyOnHidden menu={{ items }} onOpenChange={handleOnOpenChange} trigger={MENU_TRIGGER}>
          <Button aria-label={`More actions for ${name}`} onKeyDown={handleOnKeyDown} ref={buttonRef} type="text">
            <Lucide icon={EllipsisVertical} />
          </Button>
        </Dropdown>
      </Tooltip>
    </span>
  );
}

export default getColumns;
