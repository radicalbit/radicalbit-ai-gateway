import { numberFormatterInt } from '@Src/constants';
import { BarChart } from '@radicalbit/radicalbit-design-system';
import { formatResetsIn } from './helpers';
import useNowSeconds from './use-now-seconds';

const STATUS_TO_TYPE = {
  ok: 'success',
  warning: 'warning',
  critical: 'error',
};

/**
 * @typedef {object} LimitConsumptionProps
 * @property {string} algorithm The limit's window type: a Fixed window with nothing consumed has not started.
 * @property {{ windowEndTime: number, windowFilledPercentage: number, windowFilledSize: number, windowStatus: 'ok' | 'warning' | 'critical' }} [bar] The limit's entry in a consumption stream; nothing renders until it arrives.
 */

/**
 * How much of a limit's current window is used, and when it resets.
 *
 * @param {LimitConsumptionProps} props
 */
function LimitConsumption({ algorithm, bar }) {
  const now = useNowSeconds();

  const windowFilledPercentage = bar?.windowFilledPercentage;
  const windowStatus = bar?.windowStatus;

  const percentage = numberFormatterInt(windowFilledPercentage);
  const resetsIn = formatResetsIn({ algorithm, bar, now });

  if (!bar) {
    return false;
  }

  return (
    <span className="flex flex-col gap-1 min-w-40">
      <span className="flex flex-row gap-2 items-center">
        <BarChart className="w-full" type={STATUS_TO_TYPE[windowStatus]} value={percentage} />

        <small className="min-w-10 text-right">{`${percentage}%`}</small>
      </span>

      <small className="opacity-70">{resetsIn}</small>
    </span>
  );
}

export default LimitConsumption;
