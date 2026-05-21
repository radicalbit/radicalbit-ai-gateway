import dayjs from 'dayjs';

/**
 * Returns a formatted date label based on the provided timestamp and granularity.
 *
 * @param {Object} params - Parameters for label generation.
 * @param {number} params.ts - Unix timestamp (in seconds).
 * @param {'days' | 'weeks' | 'months' | 'hours'} params.granularity - Level of time granularity.
 * @param {'xaxis' | 'tooltip'} params.type - Context where the label will be used.
 *
 * @returns {string} Formatted date label.
 */
const chartTsToDate = ({ ts, granularity, type }) => {
  switch (type) {
    case 'xaxis': {
      switch (granularity) {
        case 'days': {
          const date = dayjs.unix(ts);
          return date.format('DD MMM');
        }

        case 'weeks': {
          const start = dayjs.unix(ts).startOf('isoWeek'); // Monday
          const end = start.add(6, 'day'); // Sunday
          return `${start.format('D')} to ${end.format('D MMM')}`;
        }

        case 'months': {
          const start = dayjs.unix(ts).startOf('isoWeek'); // Monday
          const end = start.add(6, 'day'); // Sunday
          return end.format('MMM YY');
        }

        case 'hours': {
          const date = dayjs.unix(ts);
          return date.format('h a');
        }

        default: return undefined;
      }
    }

    case 'tooltip': {
      switch (granularity) {
        case 'days': {
          const date = dayjs.unix(ts);
          return date.format('DD MMM');
        }

        case 'weeks': {
          const start = dayjs.unix(ts).startOf('isoWeek'); // Monday
          const end = start.add(6, 'day'); // Sunday
          return `${start.format('D')} to ${end.format('D MMM')}`;
        }

        case 'months': {
          const start = dayjs.unix(ts).startOf('isoWeek'); // Monday
          const end = start.add(6, 'day'); // Sunday
          return end.format('MMM YY');
        }

        case 'hours': {
          const date = dayjs.unix(ts);
          return date.format('DD MMM - h a');
        }

        default: return undefined;
      }
    }

    default: return undefined;
  }
};

export default chartTsToDate;
