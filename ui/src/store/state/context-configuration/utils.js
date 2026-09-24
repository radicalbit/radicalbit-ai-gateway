import { SortOrderEnum } from '@Src/constants';
import { initialState } from '@State/context-configuration';
import isArray from 'lodash/isArray';
import qs from 'query-string';

const CURRENT_PAGE = '_page';
const PAGE_SIZE = '_limit';
const SORT = '_sort';
const SORT_ORDER_PARAM = '_order';

export const queryString2configuration = (namespace, queryString) => {
  if (!queryString) {
    return initialState[namespace];
  }

  const parsed = qs.parse(queryString);
  const { [CURRENT_PAGE]: current,
    [PAGE_SIZE]: pageSize,
    [SORT]: sortName,
    [SORT_ORDER_PARAM]: sortOrder,
    ...other } = parsed;

  const pagination = current && pageSize && typeof current === 'string' && typeof pageSize === 'string'
    ? {
      current: parseInt(current, 10),
      pageSize: parseInt(pageSize, 10),
    }
    : initialState[namespace].pagination;

  const filters = Object.keys(other).reduce(
    (acc, key) => {
      const val = isArray(other[key]) ? other[key] : [other[key]];
      return { ...acc, [key]: val };
    },
    {},
  );

  const sorter = sortName && sortOrder && typeof sortName === 'string' && typeof sortOrder === 'string'
    ? { [sortName]: sortOrder.toLowerCase() === 'asc' ? SortOrderEnum.ASCEND : SortOrderEnum.DESCEND }
    : initialState[namespace].sorter;

  return { pagination, filters, sorter };
};
