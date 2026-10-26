import HtmlAnchor from '@Components/html-anchor';
import { Popover } from '@radicalbit/radicalbit-design-system';
import { LIMIT_CATEGORY_LABELS, WINDOW_TYPE_LABELS } from './constants';
import {
  formatLimitValue, formatLimitWindow, formatLimitsCount, sortLimits,
} from './helpers';

function LimitsSummary({ limits = [], onManage }) {
  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  if (!limits.length) {
    return '--';
  }

  const count = formatLimitsCount(limits.length);

  return (
    <Popover
      arrow={false}
      content={<Content limits={limits} onManage={onManage} />}
      placement="bottomLeft"
      title={<strong>Limits</strong>}
    >
      <HtmlAnchor onClick={handleOnClick}>{count}</HtmlAnchor>
    </Popover>
  );
}

function Content({ limits, onManage }) {
  const handleOnManage = (e) => {
    e.stopPropagation();
    onManage();
  };

  const lines = sortLimits(limits).map((limit) => <LimitLine key={limit.uuid} limit={limit} />);
  const manageLink = onManage ? <HtmlAnchor onClick={handleOnManage}>Manage limits</HtmlAnchor> : false;

  return (
    <div className="flex flex-col gap-2">
      {lines}

      {manageLink}
    </div>
  );
}

function LimitLine({ limit }) {
  const algorithm = limit?.algorithm;
  const category = limit?.category;
  const value = limit?.value;
  const windowSize = limit?.windowSize;

  const categoryText = `${LIMIT_CATEGORY_LABELS[category]} · `;
  const maxText = `${formatLimitValue(category, value)} / ${formatLimitWindow(windowSize)}`;
  const windowTypeText = ` · ${WINDOW_TYPE_LABELS[algorithm]}`;

  return (
    <span>
      <strong>{categoryText}</strong>

      {maxText}

      <span className="opacity-70">{windowTypeText}</span>
    </span>
  );
}

export default LimitsSummary;
