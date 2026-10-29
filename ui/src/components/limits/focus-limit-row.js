const focusLimitRow = (index) => {
  requestAnimationFrame(() => {
    const rows = document.querySelectorAll('.ant-modal [data-limit-row]');
    const row = rows[Math.min(index, rows.length - 1)];

    row?.querySelector('input:not([disabled])')?.focus();
  });
};

export default focusLimitRow;
