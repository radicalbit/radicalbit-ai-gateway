import { numberFormatterFloat, numberFormatterInt } from '@Src/constants';
import { BarChart, Popover } from '@radicalbit/radicalbit-design-system';

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
    render: (progressBar, record) => <BudgetLimit progressBar={progressBar} routeName={record.routeName} />,
  },
  {
    title: 'Tokens limit',
    dataIndex: 'progressBar',
    render: (progressBar, record) => <TokensLimit progressBar={progressBar} routeName={record.routeName} />,
  },
  {
    title: 'Rate limit',
    dataIndex: 'progressBar',
    render: (progressBar, record) => <RateLimit progressBar={progressBar} routeName={record.routeName} />,
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

function BudgetLimit({ progressBar, routeName }) {
  const budget = progressBar?.budget;
  const value = numberFormatterInt(budget?.windowFilledPercentage ?? DEFAULT_VALUE);
  const status = budget?.windowStatus ?? DEFAULT_STATUS;
  const type = STATUS_TO_TYPE[status];

  if (!budget) {
    return (
      <div className="flex flex-row gap-2 items-center">
        <BarChart
          className="w-full"
          type={type}
          value={value}
        />

        <small className="flex min-w-20">--</small>
      </div>
    );
  }

  return (
    <Popover
      content={<BudgetLimitPopoverContent budget={budget} routeName={routeName} />}
      minWidth="250"
      title={<strong>Budget limit</strong>}
    >
      <div className="flex flex-row gap-2 items-center">
        <BarChart
          className="w-full"
          type={type}
          value={value}
        />

        <small className="flex min-w-20">{`${value}%`}</small>
      </div>
    </Popover>
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

function TokensLimit({ progressBar, routeName }) {
  const tokenInput = progressBar?.tokenInput;
  const tokenOutput = progressBar?.tokenOutput;

  const inputValue = numberFormatterInt(tokenInput?.windowFilledPercentage ?? DEFAULT_VALUE);
  const inputStatus = tokenInput?.windowStatus ?? DEFAULT_STATUS;
  const inputType = STATUS_TO_TYPE[inputStatus];

  const outputValue = numberFormatterInt(tokenOutput?.windowFilledPercentage ?? DEFAULT_VALUE);
  const outputStatus = tokenOutput?.windowStatus ?? DEFAULT_STATUS;
  const outputType = STATUS_TO_TYPE[outputStatus];

  const hasTokenData = tokenInput || tokenOutput;

  if (!hasTokenData) {
    return (
      <div className="flex flex-col gap-2 ">
        <div className="flex flex-row gap-2 items-center">
          <small key="input" className="min-w-20">Input</small>

          <BarChart
            className="w-full"
            type={inputType}
            value={inputValue}
          />

          <small className="flex min-w-20">--</small>
        </div>

        <div className="flex flex-row gap-2 items-center">
          <small key="output" className="min-w-20">Output</small>

          <BarChart
            className="w-full"
            type={outputType}
            value={outputValue}
          />

          <small className="min-w-20">--</small>
        </div>
      </div>
    );
  }

  return (
    <Popover
      content={<TokensLimitPopoverContent routeName={routeName} tokenInput={tokenInput} tokenOutput={tokenOutput} />}
      minWidth="250"
      title={<strong>Token limit</strong>}
    >
      <div className="flex flex-col gap-2 ">
        <div className="flex flex-row gap-2 items-center">
          <small key="input" className="min-w-20">Input</small>

          <BarChart
            className="w-full"
            type={inputType}
            value={inputValue}
          />

          <small className="flex min-w-20">{`${inputValue}%`}</small>
        </div>

        <div className="flex flex-row gap-2 items-center">
          <small key="output" className="min-w-20">Output</small>

          <BarChart
            className="w-full"
            type={outputType}
            value={outputValue}
          />

          <small className="min-w-20">{`${outputValue}%`}</small>
        </div>
      </div>
    </Popover>
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

function RateLimit({ progressBar, routeName }) {
  const rate = progressBar?.rate;
  const value = numberFormatterInt(rate?.windowFilledPercentage ?? DEFAULT_VALUE);
  const status = rate?.windowStatus ?? DEFAULT_STATUS;
  const type = STATUS_TO_TYPE[status];

  if (!rate) {
    return (
      <div className="flex flex-row gap-2 items-center">
        <BarChart
          className="w-full"
          type={type}
          value={value}
        />

        <small className="min-w-20">--</small>
      </div>
    );
  }

  return (
    <Popover
      content={<RateLimitPopoverContent rate={rate} routeName={routeName} />}
      minWidth="250"
      title={<strong>Rate limit</strong>}
    >
      <div className="flex flex-row gap-2 items-center">
        <BarChart
          className="w-full"
          type={type}
          value={value}
        />

        <small className="min-w-20">{`${value}%`}</small>
      </div>
    </Popover>
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

function PopoverRow({ label, value }) {
  return (
    <div className="flex justify-between gap-2">
      <div>{label}</div>

      <div>{value}</div>
    </div>
  );
}
