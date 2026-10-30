const FOCUS_ATTEMPTS = 20;

const focusConfirmQuestion = (attempts = FOCUS_ATTEMPTS) => {
  requestAnimationFrame(() => {
    const question = document.querySelector('.ant-modal [data-confirm-question]');

    if (question) {
      question.focus();

      return;
    }

    if (attempts > 0) {
      focusConfirmQuestion(attempts - 1);
    }
  });
};

export default focusConfirmQuestion;
