import { numberFormatterInt } from '@Src/constants';
import { faSliders } from '@fortawesome/free-solid-svg-icons';
import {
  Button, Divider, FontAwesomeIcon, Popover,
} from '@radicalbit/radicalbit-design-system';

function Limits({ metrics, configuration }) {
  const rateLimitTriggered = metrics?.rateLimitTriggered;
  const tokenInputLimitTriggered = metrics?.tokenInputLimitTriggered;
  const tokenOutputLimitTriggered = metrics?.tokenOutputLimitTriggered;

  if (rateLimitTriggered === undefined && tokenInputLimitTriggered === undefined && tokenOutputLimitTriggered === undefined) {
    return (
      <Button disabled shape="circle">
        <FontAwesomeIcon icon={faSliders} />
      </Button>
    );
  }

  const hasTriggered = rateLimitTriggered > 0 || tokenInputLimitTriggered > 0 || tokenOutputLimitTriggered > 0;
  const btnType = hasTriggered ? { type: 'primary' } : { type: 'primary-light' };

  return (
    <Popover content={<PopoverContent configuration={configuration} metrics={metrics} />} minWidth="250" title={<strong>Limits</strong>}>
      <Button shape="circle" {...btnType}>
        <FontAwesomeIcon icon={faSliders} />
      </Button>
    </Popover>
  );
}

function PopoverContent({ configuration, metrics }) {
  const rateLimiting = configuration?.rateLimiting;
  const tokenLimitingInput = configuration?.tokenLimiting?.input;
  const tokenLimitingOutput = configuration?.tokenLimiting?.output;

  const rate = numberFormatterInt(metrics.rateLimitTriggered) ?? '--';
  const tokenIn = numberFormatterInt(metrics.tokenInputLimitTriggered) ?? '--';
  const tokenOut = numberFormatterInt(metrics.tokenOutputLimitTriggered) ?? '--';

  const rateLimitingalgorithm = rateLimiting?.algorithm ?? '--';
  const rateLimitingwindowSize = rateLimiting?.windowSize ?? '--';
  const rateLimitingmaxRequests = numberFormatterInt(rateLimiting?.maxRequests) ?? '--';

  const tokenLimitingInputAlgorithm = tokenLimitingInput?.algorithm ?? '--';
  const tokenLimitingInputWindowSize = tokenLimitingInput?.windowSize ?? '--';
  const tokenLimitingInputMaxTokens = numberFormatterInt(tokenLimitingInput?.maxTokens) ?? '--';

  const tokenLimitingOutputAlgorithm = tokenLimitingOutput?.algorithm ?? '--';
  const tokenLimitingOutputWindowSize = tokenLimitingOutput?.windowSize ?? '--';
  const tokenLimitingOutputMaxTokens = numberFormatterInt(tokenLimitingOutput?.maxTokens) ?? '--';

  return (
    <div className="flex flex-col">
      <PopoverRow label="Rate:" value={rate} />

      <PopoverRow label="Token in:" value={tokenIn} />

      <PopoverRow label="Token out:" value={tokenOut} />

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
