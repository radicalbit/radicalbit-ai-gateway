import Lucide from '@Components/lucide';
import { LIMIT_CATEGORIES, LIMIT_CATEGORY_LABELS, WINDOW_TYPE_LABELS } from '@Components/limits/constants';
import {
  formatLimitValue, formatLimitWindow, formatLimitsCount, formatNeverReached, formatRouteLimitWarning, getLimitWarnings, sortLimits,
} from '@Components/limits/helpers';
import RouteLimitWarnings from '@Components/limits/route-limit-warnings';
import useModals from '@Hooks/use-modals';
import { CredentialStateEnum } from '@Src/constants';
import { useGetKeyQuery } from '@State/keys/api';
import { useKeyLimitSaveWarnings } from '@State/keys/hooks';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Alert, Board, Button, DataTable, Void,
} from '@radicalbit/radicalbit-design-system';
import {
  ChevronDown, ChevronRight, Plus,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import LimitMenu from './limit-menu';
import { ScreenEnum } from './schema';

const EXPIRED_MESSAGE = 'This credential has expired: its limits can no longer be changed.';

const NO_LIMITS_TITLE = 'This credential has no limits';

const ROUTE_WARNINGS_TITLE = 'Saved. Some routes this credential reaches have a stricter limit';

const NO_LIMITS_DESCRIPTION = 'Only route and project limits apply.';

const WINDOW_INDENT = 'pl-6';

const getRowClassName = ({ header }) => (header ? 'cursor-pointer' : DataTable.ROW_NOT_CLICKABLE);

const getRowKey = ({ key }) => key;

function ListScreen() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const limits = data?.limits ?? [];

  if (!limits.length) {
    return <IsEmpty />;
  }

  return <IsSuccess />;
}

function IsEmpty() {
  return (
    <div className="flex flex-col gap-6">
      <ExpiredAlert />

      <Board
        main={<Void actions={<AddLimits />} description={NO_LIMITS_DESCRIPTION} size="small" title={NO_LIMITS_TITLE} />}
        width="100%"
      />
    </div>
  );
}

function IsSuccess() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const limits = data?.limits ?? [];

  const count = formatLimitsCount(limits.length);

  return (
    <div className="flex flex-col gap-6">
      <ExpiredAlert />

      <SavedWarnings />

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <strong>{count}</strong>

          <AddLimits />
        </div>

        <LimitsTable />
      </div>
    </div>
  );
}

function ExpiredAlert() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const isExpired = data?.state === CredentialStateEnum.EXPIRED;

  if (!isExpired) {
    return false;
  }

  return <Alert title={EXPIRED_MESSAGE} type="info" />;
}

function SavedWarnings() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { clearWarnings, warnings } = useKeyLimitSaveWarnings(uuid);

  const lines = warnings.map((warning) => formatRouteLimitWarning(warning));

  return <RouteLimitWarnings lines={lines} onClose={clearWarnings} title={ROUTE_WARNINGS_TITLE} />;
}

function AddLimits() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { write } = useFormbitContext();

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const isExpired = data?.state === CredentialStateEnum.EXPIRED;

  const handleOnAdd = () => {
    write('__metadata.screen', ScreenEnum.ADD);
  };

  if (isExpired) {
    return false;
  }

  return <Button icon={<Lucide icon={Plus} />} onClick={handleOnAdd}>Add limits</Button>;
}

function LimitsTable() {
  const { modalPayload } = useModals();
  const uuid = modalPayload?.data?.uuid;

  const { data } = useGetKeyQuery(uuid, { skip: !uuid });
  const limits = data?.limits;
  const limitWarnings = data?.limitWarnings;
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

      return [headerRow, ...categoryLimits.map((limit) => ({
        ...limit, header: false, key: limit.uuid, warnings: getLimitWarnings(limitWarnings, limit),
      }))];
    });
  }, [collapsed, limitWarnings, limits]);

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
      <span className={`flex flex-col ${WINDOW_INDENT}`}>
        <span>
          {formatLimitWindow(record?.windowSize)}

          <span className="opacity-70">{` · ${WINDOW_TYPE_LABELS[record?.algorithm]} window`}</span>
        </span>

        {(record?.warnings ?? []).map((warning) => <small key={warning.routeName} className="text-[var(--coo-warning)]">{formatNeverReached(warning)}</small>)}
      </span>
    );
  }

  const chevron = isExpanded ? ChevronDown : ChevronRight;

  return (
    <button aria-expanded={isExpanded} className="flex gap-2 items-center p-0 border-0 bg-transparent text-inherit text-left font-[inherit] cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--coo-fg-black)] font-[var(--coo-font-weight-bold)]" type="button">
      <Lucide icon={chevron} />

      {LIMIT_CATEGORY_LABELS[category]}

      <span className="font-normal opacity-70">{`(${count})`}</span>
    </button>
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

  return (
    <span onClick={handleOnClick} role="presentation">
      <LimitMenu limit={record} />
    </span>
  );
}

export default ListScreen;
