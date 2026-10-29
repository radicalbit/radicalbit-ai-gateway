const focusConfirmQuestion = () => {
  requestAnimationFrame(() => {
    document.querySelector('.ant-modal [data-confirm-question]')?.focus();
  });
};

export default focusConfirmQuestion;
