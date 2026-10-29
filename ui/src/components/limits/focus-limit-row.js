const focusLimitRow = (index) => {
  requestAnimationFrame(() => {
    const rows = document.querySelectorAll('.ant-modal [data-limit-row]');
    const row = rows[Math.min(index, rows.length - 1)];

    row?.querySelector('input')?.focus();
  });
};

export default focusLimitRow;
