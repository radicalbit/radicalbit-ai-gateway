const focusLimitMenu = (limitUuid) => {
  requestAnimationFrame(() => {
    const menus = [...document.querySelectorAll('.ant-modal [data-limit-menu]')];
    const menu = menus.find((element) => element.dataset.limitMenu === limitUuid) ?? menus[0];

    (menu ?? document.querySelector('.ant-modal-body button'))?.focus();
  });
};

export default focusLimitMenu;
