import { WINDOW_STATUS_LABELS } from '@Components/limits/constants';
import { formatCount } from '@Components/limits/helpers';

const STATUS_ORDER = Object.keys(WINDOW_STATUS_LABELS);

const CHANGE_FILTER = 'Change the Limit status filter to see them.';

const formatStatuses = (windowStatuses) => {
  const names = STATUS_ORDER
    .filter((status) => windowStatuses.includes(status))
    .map((status) => WINDOW_STATUS_LABELS[status]);

  if (names.length === 1) {
    return names[0];
  }

  return `${names.slice(0, -1).join(', ')} or ${names.at(-1)}`;
};

export const parseWindowStatuses = (param) => (param ? param.split(',') : [])
  .filter((status) => STATUS_ORDER.includes(status));

export const filterBudgetsByStatus = ({ limits, consumption, windowStatuses }) => {
  if (!windowStatuses.length || !consumption) {
    return limits;
  }

  return limits.filter(({ uuid }) => windowStatuses.includes(consumption[uuid]?.windowStatus));
};

export const formatNoBudgetMatches = ({ count, windowStatuses }) => {
  const verb = count === 1 ? 'is' : 'are';

  return `None of this project's ${formatCount(count, 'budget')} ${verb} ${formatStatuses(windowStatuses)} right now. ${CHANGE_FILTER}`;
};

export const formatNoRouteMatches = (windowStatuses) => `No route is ${formatStatuses(windowStatuses)} right now. ${CHANGE_FILTER}`;
