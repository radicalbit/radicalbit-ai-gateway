import InfoPopover from '@Components/info-popover';
import { Pin } from '@radicalbit/radicalbit-design-system';

const LIVE_HELP = 'Updates in real time.';

function LivePin() {
  return (
    <InfoPopover content={LIVE_HELP}>
      <Pin noMargins size="micro" type="animated" />

      <span className="sr-only">{LIVE_HELP}</span>
    </InfoPopover>
  );
}

export default LivePin;
