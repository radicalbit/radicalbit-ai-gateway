import Lucide from '@Components/lucide';
import { LIMIT_CATEGORY_LABELS } from '@Components/limits/constants';
import { formatCount, formatLimitValue, formatLimitWindow } from '@Components/limits/helpers';
import { CredentialStateEnum } from '@Src/constants';
import { useFormbitContext } from '@radicalbit/formbit';
import {
  Button, DataTable, Segmented,
} from '@radicalbit/radicalbit-design-system';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { areRowsValid, getConflicts, getPreview } from './helpers';
import useMembers from './use-members';

const ChoiceEnum = {
  SKIP: 'skip',
  OVERWRITE: 'overwrite',
};

const CHOICE_OPTIONS = [
  { label: 'Skip', value: ChoiceEnum.SKIP },
  { label: 'Overwrite', value: ChoiceEnum.OVERWRITE },
];

const EXPIRED_MESSAGE = 'Expired: receives the limits, can\'t use them';

const getRowClassName = ({ isHeader }) => (isHeader ? 'cursor-pointer' : DataTable.ROW_NOT_CLICKABLE);

const getRowKey = ({ key }) => key;

function Preview() {
  const { form } = useFormbitContext();
  const rows = form?.limits ?? [];

  const { members, limitsByKey } = useMembers();

  if (!areRowsValid(rows)) {
    return (
      <div className="flex flex-col gap-2">
        <strong>Preview</strong>

        <span className="opacity-70">Fill in the limits to see who receives them.</span>
      </div>
    );
  }

  const preview = getPreview({ limitsByKey, members, rows });
  const conflicts = getConflicts(preview);

  const conflictsMessage = conflicts.length
    ? `${formatCount(conflicts.length, 'limit')} already set on some credentials: skipped unless you choose Overwrite.`
    : 'No credential already has these limits.';

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <strong>Preview</strong>

        <ChooseAll conflicts={conflicts} />
      </div>

      <span className="text-xs opacity-70">{conflictsMessage}</span>

      <PreviewTable preview={preview} />
    </div>
  );
}

function ChooseAll({ conflicts }) {
  const { write } = useFormbitContext();

  const handleOnSkipAll = () => {
    write('overwrite', []);
  };

  const handleOnOverwriteAll = () => {
    write('overwrite', conflicts.map(({ key }) => key));
  };

  if (!conflicts.length) {
    return false;
  }

  return (
    <div className="flex gap-2">
      <Button onClick={handleOnSkipAll} size="small" type="text">Skip all</Button>

      <Button onClick={handleOnOverwriteAll} size="small" type="text">Overwrite all</Button>
    </div>
  );
}

function PreviewTable({ preview }) {
  const [collapsed, setCollapsed] = useState(new Set());

  const dataSource = preview.flatMap(({ items, member }) => {
    const conflictCount = items.filter(({ existing }) => existing).length;
    const headerRow = {
      key: `header:${member.uuid}`, conflictCount, isHeader: true, member,
    };

    if (collapsed.has(member.uuid)) {
      return [headerRow];
    }

    return [headerRow, ...items.map((item) => ({ ...item, isHeader: false, member }))];
  });

  const handleOnToggle = (memberUuid) => {
    const next = new Set(collapsed);

    if (next.has(memberUuid)) {
      next.delete(memberUuid);
    } else {
      next.add(memberUuid);
    }

    setCollapsed(next);
  };

  const handleOnRow = (record) => {
    if (!record.isHeader) {
      return {};
    }

    const handleOnClick = () => {
      handleOnToggle(record.member.uuid);
    };

    return { onClick: handleOnClick };
  };

  const columns = [
    {
      key: 'name',
      render: (_, record) => <NameCell isCollapsed={collapsed.has(record.member.uuid)} record={record} />,
    },
    {
      key: 'change',
      render: (_, record) => <ChangeCell record={record} />,
    },
    {
      key: 'choice',
      align: 'right',
      render: (_, record) => <ChoiceCell record={record} />,
    },
  ];

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

function NameCell({ isCollapsed, record }) {
  const { isHeader, limit, member } = record;

  if (!isHeader) {
    return <span className="pl-6">{`${LIMIT_CATEGORY_LABELS[limit.category]} · ${formatLimitWindow(limit.windowSize)}`}</span>;
  }

  const chevron = isCollapsed ? ChevronRight : ChevronDown;

  return (
    <div className="flex items-center gap-2">
      <Lucide icon={chevron} />

      <div className="flex flex-col">
        <strong>{member.name}</strong>

        <ExpiredMark member={member} />
      </div>
    </div>
  );
}

// Expired credentials still receive the limits: say so
function ExpiredMark({ member }) {
  if (member.state !== CredentialStateEnum.EXPIRED) {
    return false;
  }

  return <small className="text-[var(--coo-error)]">{EXPIRED_MESSAGE}</small>;
}

function ChangeCell({ record }) {
  const { conflictCount, existing, isHeader, limit } = record;

  if (isHeader) {
    return conflictCount
      ? <small className="text-[var(--coo-warning)]">{`${conflictCount} already set`}</small>
      : <small className="opacity-70">all new</small>;
  }

  if (!existing) {
    return `New · ${formatLimitValue(limit.category, limit.value)}`;
  }

  return `${formatLimitValue(limit.category, existing.value)} → ${formatLimitValue(limit.category, limit.value)} / ${formatLimitWindow(limit.windowSize)}`;
}

function ChoiceCell({ record }) {
  const { form, write } = useFormbitContext();
  const overwrite = form?.overwrite ?? [];

  const { existing, isHeader, key } = record;

  if (isHeader || !existing) {
    return false;
  }

  const handleOnChange = (value) => {
    const others = overwrite.filter((item) => item !== key);
    write('overwrite', value === ChoiceEnum.OVERWRITE ? [...others, key] : others);
  };

  // Every conflict starts as Skip: nothing is overwritten silently
  const value = overwrite.includes(key) ? ChoiceEnum.OVERWRITE : ChoiceEnum.SKIP;

  return <Segmented onChange={handleOnChange} options={CHOICE_OPTIONS} size="small" value={value} />;
}

export default Preview;
