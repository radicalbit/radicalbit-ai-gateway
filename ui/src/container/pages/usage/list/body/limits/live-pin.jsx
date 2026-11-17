import InfoPopover from '@Components/info-popover';
import { Pin } from '@radicalbit/radicalbit-design-system';

function LivePin() {
  return (
    <InfoPopover content="Updates in real time">
      <Pin noMargins size="micro" type="animated" />

      <span className="sr-only">Updates in real time</span>
    </InfoPopover>
  );
}

export default LivePin;
