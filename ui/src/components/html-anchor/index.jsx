import './_styles.less';

function HtmlAnchor({ children, className = '', role, ...rest }) {
  const css = `c-anchor ${className}`;

  // Without href an <a> is neither focusable nor exposed as a link: restore both when it acts on click
  const { href, onClick, onKeyDown } = rest;
  const isClickOnly = !!onClick && !href;

  const handleOnKeyDown = (e) => {
    if (e.key === 'Enter') {
      onClick(e);
    }

    onKeyDown?.(e);
  };

  const interactiveProps = isClickOnly
    ? { onKeyDown: handleOnKeyDown, role: role ?? 'link', tabIndex: 0 }
    : { role };

  return <a className={css} {...rest} {...interactiveProps}>{children}</a>;
}

export default HtmlAnchor;
