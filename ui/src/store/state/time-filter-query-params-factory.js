import dayjs from 'dayjs';
import timezone from 'dayjs/plugin/timezone';

dayjs.extend(timezone);

const secondToTimezonedString = (seconds) => dayjs.unix(seconds).tz(Intl.DateTimeFormat().resolvedOptions().timeZone).format();
/**
 * @typedef {Object} Args
 * @property {number|string} [from] - Start timestamp (unix seconds). Used when gte is falsy.
 * @property {number|string} [to] - End timestamp (unix seconds). Used when gte is falsy.
 * @property {number} [gte] - Seconds ago for relative range (e.g., 3600 = last hour). Overrides from/to.
 * @property {Record<string, string>|Array<[string, string]>|string} [init={}] - Initial URLSearchParams constructor input.
 * @property {boolean} [withTimezone=false] - Convert the from e to in iso string with timezone in it.
 */

/**
 * Creates URL search parameters for time-based API queries with saved tokens.
 * Supports either absolute date range (from/to) or relative time (gte seconds ago).
 *
 * @param {Args} args - Function argument
 * @returns {URLSearchParams} New params instance with _with_saved_tokens=true and time range.
 *
 * @example
 * const params1 = queryParamsFactory({ from: 1735670400, to: 1735674000 });
 * const params2 = queryParamsFactory({ gte: 3600 }); // Last hour
 * const params3 = queryParamsFactory({ init: { page: '1' } });
 */
const timeFiltersQueryParamFactory = ({ from, to, gte, init, withTimezone }) => {
  const params = new URLSearchParams(init);

  if (gte) {
    const f = withTimezone
      ? secondToTimezonedString(dayjs().subtract(gte, 'second').unix())
      : dayjs().subtract(gte, 'second').unix();

    params.append('_from', f);
  } else {
    if (from) {
      const f = withTimezone
        ? secondToTimezonedString(from)
        : from;

      params.append('_from', f);
    }

    if (to) {
      const t = withTimezone
        ? secondToTimezonedString(to)
        : to;

      params.append('_to', t);
    }
  }

  return params;
};

export default timeFiltersQueryParamFactory;
