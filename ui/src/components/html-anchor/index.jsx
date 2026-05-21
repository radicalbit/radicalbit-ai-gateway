import './_styles.less';

function HtmlAnchor({ children, className = '', ...rest }) {
  const css = `c-anchor ${className}`;

  return <a className={css} {...rest}>{children}</a>;
}

export default HtmlAnchor;
