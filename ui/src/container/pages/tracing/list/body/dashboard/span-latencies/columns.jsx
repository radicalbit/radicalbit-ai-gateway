import { formatMs } from '@Src/helpers/column-formatters';
import { faChevronDown, faChevronRight } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@radicalbit/radicalbit-design-system';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

const EXPANDED_PARAM = 'expandedSpanCategories';

const columns = [
  {
    title: '',
    dataIndex: 'name',
    align: 'left',
    width: 600,
    render: (value, record) => <Name record={record} value={value} />,
  },
  {
    title: 'p50',
    dataIndex: 'p50',
    align: 'right',
    render: formatMs,
  },
  {
    title: 'p90',
    dataIndex: 'p90',
    align: 'right',
    render: formatMs,
  },
  {
    title: 'p95',
    dataIndex: 'p95',
    align: 'right',
    render: formatMs,
  },
  {
    title: 'p99',
    dataIndex: 'p99',
    align: 'right',
    render: formatMs,
  },
];

function Name({ value, record }) {
  const [searchParams] = useSearchParams();

  const expandedCategories = useMemo(() => {
    const param = searchParams.get(EXPANDED_PARAM);

    if (!param) {
      return new Set();
    }

    return new Set(param.split(','));
  }, [searchParams]);

  if (!record.header) {
    return <span style={{ paddingLeft: 24 }}>{value}</span>;
  }

  const isExpanded = expandedCategories.has(value);
  const icon = isExpanded ? faChevronDown : faChevronRight;

  return (
    <div className="flex items-center gap-2 font-[var(--coo-font-weight-bold)]">
      <FontAwesomeIcon icon={icon} size="small" />

      {value}

      <span className="font-normal color-secondary-01">
        {`(${record.spanCount})`}
      </span>
    </div>
  );
}

export default columns;
