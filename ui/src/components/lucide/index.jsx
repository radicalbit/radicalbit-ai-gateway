import './styles.less';

function Lucide({ icon: Icon, size = 'md', className = '', ...rest }) {
  return <Icon className={`c-lucide c-lucide--size-${size} ${className}`} {...rest} />;
}

export default Lucide;
