const SIZE_CLASSNAMES = {
  md: 'w-5 h-5',
};

function Lucide({ icon: Icon, size = 'md', className = '', ...rest }) {
  const sizeClassName = SIZE_CLASSNAMES[size] ?? SIZE_CLASSNAMES.md;

  return <Icon className={`inline-block align-middle ${sizeClassName} ${className}`} {...rest} />;
}

export default Lucide;
