import { Popover } from '@radicalbit/radicalbit-design-system';

const TRIGGER = ['hover', 'focus'];

function InfoPopover({ children, ...rest }) {
  return (
    <Popover trigger={TRIGGER} {...rest}>
      <span
        className="inline-flex rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--coo-fg-black)]"
        role="button"
        tabIndex={0}
      >
        {children}
      </span>
    </Popover>
  );
}

export default InfoPopover;
