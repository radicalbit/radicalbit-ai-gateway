import InfoPopover from '@Components/info-popover';
import { Pin } from '@radicalbit/radicalbit-design-system';

const LIVE_HELP = 'Live: usage updates on its own while this page is open.';

/**
 * A column title followed by an animated pin, for a column whose values update while the page is open.
 *
 * @typedef {object} LiveColumnTitleProps
 * @property {string} title
 */

/**
 * @param {LiveColumnTitleProps} props
 */
function LiveColumnTitle({ title }) {
  return (
    <div className="flex items-center gap-2">
      {title}

      <InfoPopover childClassName="flex" content={LIVE_HELP}>
        <Pin noMargins size="micro" type="animated" />

        <span className="sr-only">{LIVE_HELP}</span>
      </InfoPopover>
    </div>
  );
}

export default LiveColumnTitle;
