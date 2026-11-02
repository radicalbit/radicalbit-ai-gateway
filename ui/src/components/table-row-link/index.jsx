import { Link, useLocation } from 'react-router-dom';

function TableRowLink({ children, keepSearch = false, to }) {
  const { search } = useLocation();

  const href = keepSearch ? `${to}${search}` : to;

  const handleOnClick = (event) => {
    event.stopPropagation();
  };

  return (
    <Link
      className="!text-inherit !no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--coo-fg-black)]"
      onClick={handleOnClick}
      to={href}
    >
      {children}
    </Link>
  );
}

export default TableRowLink;
