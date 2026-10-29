const focusDeleteQuestion = () => {
  requestAnimationFrame(() => {
    document.querySelector('.ant-modal [data-delete-question]')?.focus();
  });
};

export default focusDeleteQuestion;
