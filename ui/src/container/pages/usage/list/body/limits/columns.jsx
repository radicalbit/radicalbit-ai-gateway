import IconBadge from '@Components/icon-badge';
import InfoPopover from '@Components/info-popover';
import Lucide from '@Components/lucide';
import { numberFormatterFloat, numberFormatterInt } from '@Src/constants';
import { useGetProjectBudgetWithRange } from '@State/usage/vertical-hooks';
import { BarChart } from '@radicalbit/radicalbit-design-system';
import {
  Hourglass, TableColumnsSplit, Timer, Wallet,
} from 'lucide-react';

const STATUS_TO_TYPE = {
  ok: 'success',
  warning: 'warning',
  critical: 'error',
};

const DEFAULT_VALUE = 0;
const DEFAULT_STATUS = 'ok';

const SECONDS_PER_DAY = 86400;
const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_MINUTE = 60;

function formatWindowLength(seconds) {
  if (!seconds) {
    return '--';
  }

  if (seconds >= SECONDS_PER_DAY) {
    return `${seconds / SECONDS_PER_DAY} day`;
  }

  if (seconds >= SECONDS_PER_HOUR) {
    return `${seconds / SECONDS_PER_HOUR} hour`;
  }

  if (seconds >= SECONDS_PER_MINUTE) {
    return `${seconds / SECONDS_PER_MINUTE} min`;
  }

  return `${seconds} sec`;
}

const columns = [
  {
    title: 'Route',
    dataIndex: 'routeName',
    align: 'left',
    render: (routeName) => <RouteName routeName={routeName} />,
  },
  {
    title: 'Budget limit',
    dataIndex: 'progressBar',
    key: 'budget',
    render: (progressBar) => <BudgetLimit progressBar={progressBar} />,
  },
  {
    title: '',
    dataIndex: 'progressBar',
    key: 'budget-icon',
    width: '64px',
    render: (progressBar, record) => <BudgetIcon progressBar={progressBar} routeName={record.routeName} />,
  },
  {
    title: 'Tokens limit',
    dataIndex: 'progressBar',
    key: 'tokens',
    render: (progressBar) => <TokensLimit progressBar={progressBar} />,
  },
  {
    title: '',
    dataIndex: 'progressBar',
    key: 'tokens-icon',
    width: '64px',
    render: (progressBar, record) => <TokensIcon progressBar={progressBar} routeName={record.routeName} />,
  },
  {
    title: 'Rate limit',
    dataIndex: 'progressBar',
    key: 'rate',
    render: (progressBar) => <RateLimit progressBar={progressBar} />,
  },
  {
    title: '',
    dataIndex: 'progressBar',
    key: 'rate-icon',
    width: '64px',
    render: (progressBar, record) => <RateIcon progressBar={progressBar} routeName={record.routeName} />,
  },
  {
    title: 'Duration limit',
    dataIndex: 'progressBar',
    key: 'duration',
    render: (progressBar) => <DurationLimit progressBar={progressBar} />,
  },
  {
    title: '',
    dataIndex: 'progressBar',
    key: 'duration-icon',
    width: '64px',
    render: (progressBar, record) => <DurationIcon progressBar={progressBar} routeName={record.routeName} />,
  },
  {
    title: '',
    dataIndex: 'margin-right',
    key: 'margin-right',
    width: '10px',
  },
];

export default columns;

function RouteName({ routeName }) {
  return <span className="font-bold">{routeName}</span>;
}

function BudgetLimit({ progressBar }) {
  const { data, isLoading } = useGetProjectBudgetWithRange();
  const limits = data?.limits ?? [];

  const budget = progressBar?.budget;
  const value = numberFormatterInt(budget?.windowFilledPercentage ?? DEFAULT_VALUE);
  const status = budget?.windowStatus ?? DEFAULT_STATUS;
  const type = STATUS_TO_TYPE[status];

  if (isLoading) {
    return '--';
  }

  if (limits.length) {
    return (
      <InfoPopover content="Routes can't set their own budget. Spend on this route counts toward the project budget.">
        <span>Project budget</span>
      </InfoPopover>
    );
  }

  if (!budget) {
    return (
      <div className="flex flex-row gap-4 items-center">
        <BarChart className="w-full" type={type} value={value} />

        <small className="min-w-8 text-right">--</small>
      </div>
    );
  }

  return (
    <div className="flex flex-row gap-4 items-center">
      <BarChart className="w-full" type={type} value={value} />

      <small className="min-w-8 text-right">{`${value}%`}</small>
    </div>
  );
}

function BudgetIcon({ progressBar, routeName }) {
  const { data, isLoading } = useGetProjectBudgetWithRange();
  const limits = data?.limits ?? [];

  const budget = progressBar?.budget;

  if (isLoading || limits.length) {
    return false;
  }

  if (!budget) {
    return <IconBadge aria-label="Budget limit not set" disabled size="small"><Lucide icon={Wallet} /></IconBadge>;
  }

  return (
    <InfoPopover content={<BudgetLimitPopoverContent budget={budget} routeName={routeName} />} minWidth="250" title={<strong>Budget limit</strong>}>
      <IconBadge aria-label="Budget limit" size="small" type="primary-light"><Lucide icon={Wallet} /></IconBadge>
    </InfoPopover>
  );
}

function BudgetLimitPopoverContent({ budget, routeName }) {
  const window = formatWindowLength(budget.windowLength);
  const current = `${numberFormatterFloat(budget.windowFilledSize)}/${numberFormatterFloat(budget.windowSize)}`;

  return (
    <div className="flex flex-col">
      <PopoverRow label="Route:" value={routeName} />

      <PopoverRow label="Window:" value={window} />

      <PopoverRow label="Current:" value={current} />
    </div>
  );
}

function TokensLimit({ progressBar }) {
  const tokenInput = progressBar?.tokenInput;
  const tokenOutput = progressBar?.tokenOutput;

  const inputValue = numberFormatterInt(tokenInput?.windowFilledPercentage ?? DEFAULT_VALUE);
  const inputStatus = tokenInput?.windowStatus ?? DEFAULT_STATUS;
  const inputType = STATUS_TO_TYPE[inputStatus];

  const outputValue = numberFormatterInt(tokenOutput?.windowFilledPercentage ?? DEFAULT_VALUE);
  const outputStatus = tokenOutput?.windowStatus ?? DEFAULT_STATUS;
  const outputType = STATUS_TO_TYPE[outputStatus];

  if (!tokenInput && !tokenOutput) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex flex-row gap-4 items-center">
          <small className="min-w-15">Input</small>

          <BarChart className="w-full" type={inputType} value={inputValue} />

          <small className="min-w-8 text-right">--</small>
        </div>

        <div className="flex flex-row gap-4 items-center">
          <small className="min-w-15">Output</small>

          <BarChart className="w-full" type={outputType} value={outputValue} />

          <small className="min-w-8 text-right">--</small>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-row gap-4 items-center">
        <small className="min-w-15">Input</small>

        <BarChart className="w-full" type={inputType} value={inputValue} />

        <small className="min-w-8 text-right">{`${inputValue}%`}</small>
      </div>

      <div className="flex flex-row gap-4 items-center">
        <small className="min-w-15">Output</small>

        <BarChart className="w-full" type={outputType} value={outputValue} />

        <small className="min-w-8 text-right">{`${outputValue}%`}</small>
      </div>
    </div>
  );
}

function TokensIcon({ progressBar, routeName }) {
  const tokenInput = progressBar?.tokenInput;
  const tokenOutput = progressBar?.tokenOutput;

  if (!tokenInput && !tokenOutput) {
    return <IconBadge aria-label="Token limit not set" disabled size="small"><Lucide icon={TableColumnsSplit} /></IconBadge>;
  }

  return (
    <InfoPopover content={<TokensLimitPopoverContent routeName={routeName} tokenInput={tokenInput} tokenOutput={tokenOutput} />} minWidth="250" title={<strong>Token limit</strong>}>
      <IconBadge aria-label="Token limit" size="small" type="primary-light"><Lucide icon={TableColumnsSplit} /></IconBadge>
    </InfoPopover>
  );
}

function TokensLimitPopoverContent({ routeName, tokenInput, tokenOutput }) {
  const windowInput = formatWindowLength(tokenInput?.windowLength);
  const windowOutput = formatWindowLength(tokenOutput?.windowLength);
  const currentInput = `${numberFormatterInt(tokenInput?.windowFilledSize)}/${numberFormatterInt(tokenInput?.windowSize)}`;
  const currentOutput = `${numberFormatterInt(tokenOutput?.windowFilledSize)}/${numberFormatterInt(tokenOutput?.windowSize)}`;

  return (
    <div className="flex flex-col">
      <PopoverRow label="Route:" value={routeName} />

      <PopoverRow label="Window input:" value={windowInput} />

      <PopoverRow label="Window output:" value={windowOutput} />

      <PopoverRow label="Current input:" value={currentInput} />

      <PopoverRow label="Current output:" value={currentOutput} />
    </div>
  );
}

function RateLimit({ progressBar }) {
  const rate = progressBar?.rate;
  const value = numberFormatterInt(rate?.windowFilledPercentage ?? DEFAULT_VALUE);
  const status = rate?.windowStatus ?? DEFAULT_STATUS;
  const type = STATUS_TO_TYPE[status];

  if (!rate) {
    return (
      <div className="flex flex-row gap-4 items-center">
        <BarChart className="w-full" type={type} value={value} />

        <small className="min-w-8 text-right">--</small>
      </div>
    );
  }

  return (
    <div className="flex flex-row gap-4 items-center">
      <BarChart className="w-full" type={type} value={value} />

      <small className="min-w-8 text-right">{`${value}%`}</small>
    </div>
  );
}

function RateIcon({ progressBar, routeName }) {
  const rate = progressBar?.rate;

  if (!rate) {
    return <IconBadge aria-label="Rate limit not set" disabled size="small"><Lucide icon={Timer} /></IconBadge>;
  }

  return (
    <InfoPopover content={<RateLimitPopoverContent rate={rate} routeName={routeName} />} minWidth="250" title={<strong>Rate limit</strong>}>
      <IconBadge aria-label="Rate limit" size="small" type="primary-light"><Lucide icon={Timer} /></IconBadge>
    </InfoPopover>
  );
}

function RateLimitPopoverContent({ rate, routeName }) {
  const window = formatWindowLength(rate.windowLength);
  const current = `${numberFormatterInt(rate.windowFilledSize)}/${numberFormatterInt(rate.windowSize)}`;

  return (
    <div className="flex flex-col">
      <PopoverRow label="Route:" value={routeName} />

      <PopoverRow label="Window:" value={window} />

      <PopoverRow label="Current:" value={current} />
    </div>
  );
}

function DurationLimit({ progressBar }) {
  const duration = progressBar?.duration;
  const value = numberFormatterInt(duration?.windowFilledPercentage ?? DEFAULT_VALUE);
  const status = duration?.windowStatus ?? DEFAULT_STATUS;
  const type = STATUS_TO_TYPE[status];

  if (!duration) {
    return (
      <div className="flex flex-row gap-4 items-center">
        <BarChart className="w-full" type={type} value={value} />

        <small className="min-w-8 text-right">--</small>
      </div>
    );
  }

  return (
    <div className="flex flex-row gap-4 items-center">
      <BarChart className="w-full" type={type} value={value} />

      <small className="min-w-8 text-right">{`${value}%`}</small>
    </div>
  );
}

function DurationIcon({ progressBar, routeName }) {
  const duration = progressBar?.duration;

  if (!duration) {
    return <IconBadge aria-label="Duration limit not set" disabled size="small"><Lucide icon={Hourglass} /></IconBadge>;
  }

  return (
    <InfoPopover content={<DurationLimitPopoverContent duration={duration} routeName={routeName} />} minWidth="250" title={<strong>Duration limit</strong>}>
      <IconBadge aria-label="Duration limit" size="small" type="primary-light"><Lucide icon={Hourglass} /></IconBadge>
    </InfoPopover>
  );
}

function DurationLimitPopoverContent({ duration, routeName }) {
  const window = formatWindowLength(duration.windowLength);
  const current = `${numberFormatterInt(duration.windowFilledSize)}/${numberFormatterInt(duration.windowSize)}`;

  return (
    <div className="flex flex-col">
      <PopoverRow label="Route:" value={routeName} />

      <PopoverRow label="Window:" value={window} />

      <PopoverRow label="Current:" value={current} />
    </div>
  );
}

function PopoverRow({ label, value }) {
  return (
    <div className="flex justify-between gap-2">
      <div>{label}</div>

      <div>{value}</div>
    </div>
  );
}
