import Lucide from '@Components/lucide';
import { numberFormatterInt } from '@Src/constants';
import {
  Button, Divider, Popover,
} from '@radicalbit/radicalbit-design-system';
import { SlidersHorizontal } from 'lucide-react';

function Limits({ metrics, configuration }) {
  const rateLimitTriggered = metrics?.rateLimitTriggered;
  const tokenInputLimitTriggered = metrics?.tokenInputLimitTriggered;
  const tokenOutputLimitTriggered = metrics?.tokenOutputLimitTriggered;
  const durationLimitTriggered = metrics?.durationLimitTriggered;

  if (rateLimitTriggered === undefined && tokenInputLimitTriggered === undefined && tokenOutputLimitTriggered === undefined && durationLimitTriggered === undefined) {
    return (
      <Button disabled shape="circle">
        <Lucide icon={SlidersHorizontal} />
      </Button>
    );
  }

  const hasTriggered = rateLimitTriggered > 0 || tokenInputLimitTriggered > 0 || tokenOutputLimitTriggered > 0 || durationLimitTriggered > 0;
  const btnType = hasTriggered ? { type: 'primary' } : { type: 'primary-light' };

  return (
    <Popover content={<PopoverContent configuration={configuration} metrics={metrics} />} minWidth="250" title={<strong>Limits</strong>}>
      <Button shape="circle" {...btnType}>
        <Lucide icon={SlidersHorizontal} />
      </Button>
    </Popover>
  );
}

function PopoverContent({ configuration, metrics }) {
  const rateLimiting = configuration?.rateLimiting;
  const tokenLimitingInput = configuration?.tokenLimiting?.input;
  const tokenLimitingOutput = configuration?.tokenLimiting?.output;
  const durationLimiting = configuration?.durationLimiting;

  const rate = numberFormatterInt(metrics.rateLimitTriggered) ?? '--';
  const tokenIn = numberFormatterInt(metrics.tokenInputLimitTriggered) ?? '--';
  const tokenOut = numberFormatterInt(metrics.tokenOutputLimitTriggered) ?? '--';
  const duration = numberFormatterInt(metrics.durationLimitTriggered) ?? '--';

  const rateLimitingalgorithm = rateLimiting?.algorithm ?? '--';
  const rateLimitingwindowSize = rateLimiting?.windowSize ?? '--';
  const rateLimitingmaxRequests = numberFormatterInt(rateLimiting?.maxRequests) ?? '--';

  const tokenLimitingInputAlgorithm = tokenLimitingInput?.algorithm ?? '--';
  const tokenLimitingInputWindowSize = tokenLimitingInput?.windowSize ?? '--';
  const tokenLimitingInputMaxTokens = numberFormatterInt(tokenLimitingInput?.maxTokens) ?? '--';

  const tokenLimitingOutputAlgorithm = tokenLimitingOutput?.algorithm ?? '--';
  const tokenLimitingOutputWindowSize = tokenLimitingOutput?.windowSize ?? '--';
  const tokenLimitingOutputMaxTokens = numberFormatterInt(tokenLimitingOutput?.maxTokens) ?? '--';

  const durationLimitingAlgorithm = durationLimiting?.algorithm ?? '--';
  const durationLimitingWindowSize = durationLimiting?.windowSize ?? '--';
  const durationLimitingMaxDurationSeconds = numberFormatterInt(durationLimiting?.maxDurationSeconds) ?? '--';

  return (
    <div className="flex flex-col">
      <PopoverRow label="Rate:" value={rate} />

      <PopoverRow label="Token in:" value={tokenIn} />

      <PopoverRow label="Token out:" value={tokenOut} />

      <PopoverRow label="Duration:" value={duration} />

      <Divider style={{ margin: '.5rem' }} />

      <strong>Rate Limiting</strong>

      <PopoverRow label="Algorithm:" value={rateLimitingalgorithm} />

      <PopoverRow label="Window size:" value={rateLimitingwindowSize} />

      <PopoverRow label="Max requests:" value={rateLimitingmaxRequests} />

      <Divider style={{ margin: '.5rem' }} />

      <strong>Token Limiting Input</strong>

      <PopoverRow label="Algorithm:" value={tokenLimitingInputAlgorithm} />

      <PopoverRow label="Window size:" value={tokenLimitingInputWindowSize} />

      <PopoverRow label="Max tokens:" value={tokenLimitingInputMaxTokens} />

      <Divider style={{ margin: '.5rem' }} />

      <strong>Token Limiting Output</strong>

      <PopoverRow label="Algorithm:" value={tokenLimitingOutputAlgorithm} />

      <PopoverRow label="Window size:" value={tokenLimitingOutputWindowSize} />

      <PopoverRow label="Max tokens:" value={tokenLimitingOutputMaxTokens} />

      <Divider style={{ margin: '.5rem' }} />

      <strong>Duration Limiting</strong>

      <PopoverRow label="Algorithm:" value={durationLimitingAlgorithm} />

      <PopoverRow label="Window size:" value={durationLimitingWindowSize} />

      <PopoverRow label="Max duration (s):" value={durationLimitingMaxDurationSeconds} />
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

export default Limits;
