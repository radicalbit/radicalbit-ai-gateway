import { Badge, Tooltip } from '@radicalbit/radicalbit-design-system';

const LIVE_HELP = 'Live: consumption updates in real time';

/**
 * A column title with a pulsing dot, for a column whose values stream in while the page is open.
 *
 * @typedef {object} LiveColumnTitleProps
 * @property {string} title
 */

/**
 * @param {LiveColumnTitleProps} props
 */
function LiveColumnTitle({ title }) {
  return (
    <span className="inline-flex items-center gap-2">
      {title}

      <Tooltip title={LIVE_HELP}>
        <span aria-label={LIVE_HELP} role="img">
          <Badge status="processing" />
        </span>
      </Tooltip>
    </span>
  );
}

export default LiveColumnTitle;
