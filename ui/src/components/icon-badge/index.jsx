import { Button } from '@radicalbit/radicalbit-design-system';
import classNames from 'classnames';

/**
 * @typedef {object} IconBadgeProps
 * @property {string} aria-label Accessible name of the badge (e.g. "Caching")
 * @property {React.ReactNode} children The icon
 * @property {string} [className] Merged with the badge own classes
 * @property {boolean} [disabled]
 * @property {React.Ref<HTMLSpanElement>} [ref]
 * @property {'small' | 'middle' | 'large'} [size]
 * @property {React.CSSProperties} [style]
 * @property {string} [type] Any DS Button type
 */

/**
 * Circular badge with an icon: it looks like a DS Button but it is not an action.
 * The wrapping span is the interactive surface (Popover / Tooltip triggers, row clicks),
 * the Button is only the visual part and is hidden from assistive tech and from focus.
 * @param {IconBadgeProps & React.HTMLAttributes<HTMLSpanElement>} props
 */
function IconBadge({
  'aria-label': ariaLabel,
  children,
  className,
  disabled,
  ref,
  size,
  style,
  type,
  ...rest
}) {
  return (
    <span aria-label={ariaLabel} className={classNames('inline-flex', className)} ref={ref} role="img" {...rest}>
      <Button aria-hidden disabled={disabled} shape="circle" size={size} style={style} tabIndex={-1} type={type}>
        {children}
      </Button>
    </span>
  );
}

export default IconBadge;
