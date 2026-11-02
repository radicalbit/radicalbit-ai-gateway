const FOCUS_ATTEMPTS = 20;

const focusLimitRow = (index, attempts = FOCUS_ATTEMPTS) => {
  requestAnimationFrame(() => {
    const rows = document.querySelectorAll('.ant-modal [data-limit-row]');
    const row = rows[Math.min(index, rows.length - 1)];
    const input = row?.querySelector('input:not([disabled])');

    if (input) {
      input.focus();

      return;
    }

    if (attempts > 0) {
      focusLimitRow(index, attempts - 1);
    }
  });
};

export default focusLimitRow;
