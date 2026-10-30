import HtmlAnchor from '@Components/html-anchor';
import { Popover } from '@radicalbit/radicalbit-design-system';
import { useState } from 'react';
import { LIMIT_CATEGORY_LABELS, LimitCategoryEnum, WINDOW_TYPE_LABELS } from './constants';
import {
  formatCount, formatLimitValue, formatLimitWindow, formatNeverReached, getLimitWarnings, sortLimits,
} from './helpers';

const TRIGGER = ['hover', 'focus'];

function LimitsSummary({ limits = [], noun = 'limit', onManage, warnings = [], withCategory = true }) {
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
  const neverReached = neverReachedCount ? <span className="text-[var(--coo-warning)]">{` · ${neverReachedCount} never reached`}</span> : false;

  return (
    <Popover
      arrow={false}
      content={<Content limits={limits} onManage={contentOnManage} warnings={warnings} withCategory={withCategory} />}
      onOpenChange={setIsOpen}
      open={isOpen}
      placement="bottomLeft"
      title={<strong>{title}</strong>}
      trigger={TRIGGER}
    >
      <span>
        <HtmlAnchor onClick={handleOnClick}>{count}</HtmlAnchor>

        {neverReached}
      </span>
    </Popover>
  );
}

function Content({ limits, onManage, warnings, withCategory }) {
  const handleOnManage = (e) => {
    e.stopPropagation();
    onManage();
  };

  const lines = sortLimits(limits).map((limit) => <LimitLine key={limit.uuid} limit={limit} warnings={getLimitWarnings(warnings, limit)} withCategory={withCategory} />);
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

function LimitLine({ limit, warnings, withCategory }) {
  const algorithm = limit?.algorithm;
  const category = limit?.category ?? LimitCategoryEnum.BUDGET;
  const value = limit?.value;
  const windowSize = limit?.windowSize;

  const categoryText = withCategory ? <strong>{`${LIMIT_CATEGORY_LABELS[category]} · `}</strong> : false;
  const maxText = `${formatLimitValue(category, value)} / ${formatLimitWindow(windowSize)}`;
  const windowTypeText = ` · ${WINDOW_TYPE_LABELS[algorithm]}`;

  return (
    <span className="flex flex-col">
      <span>
        {categoryText}

        {maxText}

        <span className="opacity-70">{windowTypeText}</span>
      </span>

      {warnings.map((warning) => <small key={warning.routeName} className="text-[var(--coo-warning)]">{formatNeverReached(warning)}</small>)}
    </span>
  );
}

export default LimitsSummary;
