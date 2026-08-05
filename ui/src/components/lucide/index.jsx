import classNames from 'classnames';
import './_styles.less';

const SIZE_CLASSNAMES = {
  md: 'w-5 h-5',
};

function Lucide({
  icon: Icon,
  size = 'md',
  className = '',
  disabled,
  type = 'default',
  ...rest
}) {
  const css = classNames(
    {
      [`c-lucide--type-${type}`]: type,
      'c-lucide--disabled': disabled,
    },
    'c-lucide',
  );
  const sizeClassName = SIZE_CLASSNAMES[size] ?? SIZE_CLASSNAMES.md;

  return (
    <Icon
      className={`inline-block align-middle ${sizeClassName} ${className} ${css}`}
      {...rest}
    />
  );
}

export default Lucide;
