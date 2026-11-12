import HtmlAnchor from '@Components/html-anchor';
import { Popover, SectionTitle } from '@radicalbit/radicalbit-design-system';
import { useState } from 'react';
import { LIMIT_CATEGORY_LABELS, LimitCategoryEnum, WINDOW_TYPE_LABELS } from './constants';
import {
  formatCount, formatLimitValue, formatLimitWindow, formatNeverReached, getLimitWarnings, getMostConsumed, sortLimits,
} from './helpers';
import LimitConsumption from './limit-consumption';

const TRIGGER = ['hover', 'focus'];

const STATUS_CLASS_NAMES = {
  ok: '',
  warning: 'text-[var(--coo-warning)]',
  critical: 'text-[var(--coo-error)]',
};

function LimitsSummary({
  consumption, limits = [], noun = 'limit', onManage, warnings = [], withCategory = true,
}) {
  const [isOpen, setIsOpen] = useState(false);

  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  const handleOnManage = () => {
    setIsOpen(false);
    onManage();
  };

  if (!limits.length) {
    return '--';
  }

  const count = formatCount(limits.length, noun);
  const title = withCategory ? 'Limits' : 'Budgets';
  const contentOnManage = onManage ? handleOnManage : undefined;
  const neverReachedCount = limits.filter((limit) => getLimitWarnings(warnings, limit).length).length;

  return (
    <Popover
      arrow={false}
      content={<Content consumption={consumption} limits={limits} onManage={contentOnManage} warnings={warnings} withCategory={withCategory} />}
      onOpenChange={setIsOpen}
      open={isOpen}
      placement="bottomLeft"
      title={<strong>{title}</strong>}
      trigger={TRIGGER}
    >
      <span className="inline-block">
        <SectionTitle
          size="small"
          subtitle={<Details consumption={consumption} limits={limits} neverReachedCount={neverReachedCount} />}
          title={<HtmlAnchor onClick={handleOnClick}>{count}</HtmlAnchor>}
          titleWeight="normal"
        />
      </span>
    </Popover>
  );
}

// The second line, like a subtitle: how much of the most consumed limit is used, and how many are never reached.
function Details({ consumption, limits, neverReachedCount }) {
  const mostConsumed = getMostConsumed(limits, consumption);
  const percentage = mostConsumed?.percentage;
  const status = mostConsumed?.status;

  const neverReached = `${neverReachedCount} never reached`;

  if (mostConsumed && neverReachedCount) {
    return (
      <span>
        <span className={STATUS_CLASS_NAMES[status]}>{`up to ${percentage}% used`}</span>

        <span className="text-[var(--coo-warning)]">{` · ${neverReached}`}</span>
      </span>
    );
  }

  if (mostConsumed) {
    return <span className={STATUS_CLASS_NAMES[status]}>{`up to ${percentage}% used`}</span>;
  }

  if (neverReachedCount) {
    return <span className="text-[var(--coo-warning)]">{neverReached}</span>;
  }

  return false;
}

function Content({ consumption, limits, onManage, warnings, withCategory }) {
  const handleOnManage = (e) => {
    e.stopPropagation();
    onManage();
  };

  const lines = sortLimits(limits).map((limit) => <LimitLine key={limit.uuid} bar={consumption?.[limit.uuid]} limit={limit} warnings={getLimitWarnings(warnings, limit)} withCategory={withCategory} />);
  const manageLabel = withCategory ? 'Manage limits' : 'Manage budgets';
  const manageLink = onManage ? <HtmlAnchor onClick={handleOnManage}>{manageLabel}</HtmlAnchor> : false;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        {lines}
      </div>

      {manageLink}
    </div>
  );
}

function LimitLine({ bar, limit, warnings, withCategory }) {
  const algorithm = limit?.algorithm;
  const category = limit?.category ?? LimitCategoryEnum.BUDGET;
  const value = limit?.value;
  const windowSize = limit?.windowSize;

  const categoryText = withCategory ? <strong>{`${LIMIT_CATEGORY_LABELS[category]} · `}</strong> : false;
  const maxText = `${formatLimitValue(category, value)} / ${formatLimitWindow(windowSize)}`;
  const windowTypeText = ` · ${WINDOW_TYPE_LABELS[algorithm]}`;

  return (
    <span className="flex flex-col gap-1">
      <span>
        {categoryText}

        {maxText}

        <span className="opacity-70">{windowTypeText}</span>
      </span>

      <LimitConsumption algorithm={algorithm} bar={bar} />

      {warnings.map((warning) => <small key={warning.routeName} className="text-[var(--coo-warning)]">{formatNeverReached(warning)}</small>)}
    </span>
  );
}

export default LimitsSummary;
