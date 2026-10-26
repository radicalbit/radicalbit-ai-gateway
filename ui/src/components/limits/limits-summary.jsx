import HtmlAnchor from '@Components/html-anchor';
import { Popover } from '@radicalbit/radicalbit-design-system';
import { LIMIT_CATEGORY_LABELS, LimitCategoryEnum, WINDOW_TYPE_LABELS } from './constants';
import {
  formatCount, formatLimitValue, formatLimitWindow, sortLimits,
} from './helpers';

function LimitsSummary({ limits = [], noun = 'limit', onManage, withCategory = true }) {
  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  if (!limits.length) {
    return '--';
  }

  const count = formatCount(limits.length, noun);
  const title = withCategory ? 'Limits' : 'Budgets';

  return (
    <Popover
      arrow={false}
      content={<Content limits={limits} onManage={onManage} withCategory={withCategory} />}
      placement="bottomLeft"
      title={<strong>{title}</strong>}
    >
      <HtmlAnchor onClick={handleOnClick}>{count}</HtmlAnchor>
    </Popover>
  );
}

function Content({ limits, onManage, withCategory }) {
  const handleOnManage = (e) => {
    e.stopPropagation();
    onManage();
  };

  const lines = sortLimits(limits).map((limit) => <LimitLine key={limit.uuid} limit={limit} withCategory={withCategory} />);
  const manageLabel = withCategory ? 'Manage limits' : 'Manage budgets';
  const manageLink = onManage ? <HtmlAnchor onClick={handleOnManage}>{manageLabel}</HtmlAnchor> : false;

  return (
    <div className="flex flex-col gap-2">
      {lines}

      {manageLink}
    </div>
  );
}

function LimitLine({ limit, withCategory }) {
  const algorithm = limit?.algorithm;
  const category = limit?.category ?? LimitCategoryEnum.BUDGET;
  const value = limit?.value;
  const windowSize = limit?.windowSize;

  const categoryText = withCategory ? <strong>{`${LIMIT_CATEGORY_LABELS[category]} · `}</strong> : false;
  const maxText = `${formatLimitValue(category, value)} / ${formatLimitWindow(windowSize)}`;
  const windowTypeText = ` · ${WINDOW_TYPE_LABELS[algorithm]}`;

  return (
    <span>
      {categoryText}

      {maxText}

      <span className="opacity-70">{windowTypeText}</span>
    </span>
  );
}

export default LimitsSummary;
