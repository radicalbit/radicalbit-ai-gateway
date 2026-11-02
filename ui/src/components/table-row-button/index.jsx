function TableRowButton({ children, onClick }) {
  const handleOnClick = (event) => {
    event.stopPropagation();
    onClick(event);
  };

  return (
    <button
      className="p-0 border-0 bg-transparent text-inherit text-left font-[inherit] cursor-pointer max-w-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--coo-fg-black)]"
      onClick={handleOnClick}
      type="button"
    >
      {children}
    </button>
  );
}

export default TableRowButton;
