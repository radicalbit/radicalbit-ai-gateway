import classNames from 'classnames';
import { forwardRef } from 'react';
import './_styles.less';

const SIZE_CLASSNAMES = {
  md: 'w-5 h-5',
};

const Lucide = forwardRef(({
  icon: Icon,
  size = 'md',
  className = '',
  disabled,
  type = 'default',
  onClick,
  onKeyDown,
  ...rest
}, ref) => {
  const css = classNames(
    {
      [`c-lucide--type-${type}`]: type,
      'c-lucide--disabled': disabled,
    },
    'c-lucide',
  );
  const sizeClassName = SIZE_CLASSNAMES[size] ?? SIZE_CLASSNAMES.md;

  // A clickable icon behaves as a button: focusable and activable with Enter / Space
  const handleOnKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onClick(e);
    }

    onKeyDown?.(e);
  };

  const interactiveProps = onClick
    ? { onClick, onKeyDown: handleOnKeyDown, role: 'button', tabIndex: 0 }
    : { onKeyDown };

  return (
    <Icon
      className={`inline-block align-middle ${sizeClassName} ${className} ${css}`}
      ref={ref}
      {...interactiveProps}
      {...rest}
    />
  );
});

Lucide.displayName = 'Lucide';

export default Lucide;
