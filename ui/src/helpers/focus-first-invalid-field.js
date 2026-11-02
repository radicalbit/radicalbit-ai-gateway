const FOCUSABLE = 'input:not([disabled]), textarea:not([disabled]), button:not([disabled]), [tabindex="0"]';

const focusFirstInvalidField = () => {
  requestAnimationFrame(() => {
    const field = [...document.querySelectorAll('.ant-modal .c-form-field')]
      .find((element) => element.querySelector('.c-form-field__message--error'));

    field?.querySelector(FOCUSABLE)?.focus();
  });
};

export default focusFirstInvalidField;
