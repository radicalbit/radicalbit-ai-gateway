import Lucide from '@Components/lucide';
import { LIMIT_CATEGORIES, LIMIT_CATEGORY_LABELS, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import {
  formatLimitValue, formatLimitWindow, formatLimitsCount, sortLimits,
} from '@Components/limits/helpers';
import useModals from '@Hooks/use-modals';
import { CredentialStateEnum } from '@Src/constants';
import { useGetKeyQuery } from '@State/keys/api';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Alert, Button, DataTable, Dropdown,
} from '@radicalbit/radicalbit-design-system';
import {
  ChevronDown, ChevronRight, EllipsisVertical, Plus,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import DeleteLimit from './delete-limit';
import { ScreenEnum } from './schema';

const EXPIRED_MESSAGE = 'This credential has expired: its limits can no longer be changed.';

const NO_LIMITS_MESSAGE = 'This credential has no limits: only route and project limits apply.';

// Window rows sit under their category, past the chevron
const WINDOW_INDENT = 'pl-6';

const getRowClassName = ({ header }) => (header ? 'cursor-pointer' : DataTable.ROW_NOT_CLICKABLE);

const getRowKey = ({ key }) => key;

function ListScreen() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { write } = useFormbitContext();

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const limits = data?.limits ?? [];
  const isExpired = data?.state === CredentialStateEnum.EXPIRED;

  const handleOnAdd = () => {
    write('__metadata.screen', ScreenEnum.ADD);
  };

  const expiredAlert = isExpired ? <Alert title={EXPIRED_MESSAGE} type="info" /> : false;
  const addButton = isExpired ? false : (
    <Button onClick={handleOnAdd} prefix={<Lucide icon={Plus} />} type="secondary">Add limits</Button>
  );
  const content = limits.length ? <LimitsTable /> : <span className="opacity-70">{NO_LIMITS_MESSAGE}</span>;
  const count = limits.length ? formatLimitsCount(limits.length) : 'No limits';

  return (
    <div className="flex flex-col gap-4">
      {expiredAlert}

      <div className="flex items-center justify-between">
        <strong>{count}</strong>

        {addButton}
      </div>

      {content}
    </div>
  );
}

// Grouped by category like the Span latencies table: a header row per category, its limits below when expanded
function LimitsTable() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const limits = data?.limits;
  const isExpired = data?.state === CredentialStateEnum.EXPIRED;

  const [collapsed, setCollapsed] = useState(new Set());

  const dataSource = useMemo(() => {
    const sorted = sortLimits(limits ?? []);

    return LIMIT_CATEGORIES.flatMap((category) => {
      const categoryLimits = sorted.filter((limit) => limit.category === category);

      if (!categoryLimits.length) {
        return [];
      }

      const headerRow = {
        category, count: categoryLimits.length, header: true, key: `header:${category}`,
      };

      if (collapsed.has(category)) {
        return [headerRow];
      }

      return [headerRow, ...categoryLimits.map((limit) => ({ ...limit, header: false, key: limit.uuid }))];
    });
  }, [collapsed, limits]);

  const columns = useMemo(() => [
    {
      title: '',
      key: 'name',
      render: (_, record) => <Name isExpanded={!collapsed.has(record.category)} record={record} />,
    },
    {
      title: '',
      key: 'value',
      align: 'right',
      render: (_, record) => <Max record={record} />,
    },
    {
      title: '',
      key: 'actions',
      width: '50px',
      render: (_, record) => <Actions isExpired={isExpired} record={record} />,
    },
  ], [collapsed, isExpired]);

  const handleOnToggle = (category) => {
    setCollapsed((previous) => {
      const next = new Set(previous);

      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }

      return next;
    });
  };

  const handleOnRow = (record) => {
    if (!record.header) {
      return {};
    }

    const handleOnClick = () => {
      handleOnToggle(record.category);
    };

    return { onClick: handleOnClick };
  };

  return (
    <DataTable
      columns={columns}
      dataSource={dataSource}
      onRow={handleOnRow}
      pagination={false}
      rowClassName={getRowClassName}
      rowKey={getRowKey}
      showHeader={false}
      size="small"
    />
  );
}

function Name({ isExpanded, record }) {
  const category = record?.category;
  const count = record?.count;

  if (!record?.header) {
    return (
      <span className={WINDOW_INDENT}>
        {formatLimitWindow(record?.windowSize)}

        <span className="opacity-70">{` · ${WINDOW_TYPE_LABELS[record?.algorithm]} window`}</span>
      </span>
    );
  }

  const chevron = isExpanded ? ChevronDown : ChevronRight;

  return (
    <div className="flex gap-2 items-center font-[var(--coo-font-weight-bold)]">
      <Lucide icon={chevron} />

      {LIMIT_CATEGORY_LABELS[category]}

      <span className="font-normal opacity-70">{`(${count})`}</span>
    </div>
  );
}

function Max({ record }) {
  if (record?.header) {
    return false;
  }

  return formatLimitValue(record?.category, record?.value);
}

function Actions({ isExpired, record }) {
  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  if (record?.header || isExpired) {
    return false;
  }

  const items = [{ key: 'delete', label: <DeleteLimit limit={record} /> }];

  return (
    <Dropdown menu={{ items }}>
      <Button aria-label="More actions" onClick={handleOnClick} type="text">
        <Lucide icon={EllipsisVertical} />
      </Button>
    </Dropdown>
  );
}

export default ListScreen;
