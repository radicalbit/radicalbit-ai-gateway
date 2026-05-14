import { actions as layoutActions } from '@State/layout';

export const MAIN_LAYOUT_CONFIGURATION = [
  layoutActions.showHeader,
  layoutActions.showLeftColumn,
  layoutActions.showSecondaryColumn,
  layoutActions.hideRightColumn,
];

export const DETAIL_LAYOUT_CONFIGURATION = [
  layoutActions.showHeader,
  layoutActions.showLeftColumn,
  layoutActions.hideSecondaryColumn,
  layoutActions.showRightColumn,
];

export const WIDE_MAIN_LAYOUT_CONFIGURATION = [
  layoutActions.showHeader,
  layoutActions.showLeftColumn,
  layoutActions.hideSecondaryColumn,
  layoutActions.hideRightColumn,
];

export const EXPERIMENTAL_SET_DARK_MODE = [
  layoutActions.darkenMainContent,
  layoutActions.darkenMainHeader,
  layoutActions.darkenRightColumn,
  layoutActions.darkenRightColumnHeader,
  layoutActions.darkenLeftColumn,
  layoutActions.darkenLeftColumnHeader,
  layoutActions.darkenSecondaryColumn,
  layoutActions.darkenSecondaryColumnHeader,
];

export const EXPERIMENTAL_SET_LIGHT_MODE = [
  layoutActions.lightenMainContent,
  layoutActions.lightenMainHeader,
  layoutActions.lightenRightColumn,
  layoutActions.lightenRightColumnHeader,
  layoutActions.lightenLeftColumn,
  layoutActions.lightenLeftColumnHeader,
  layoutActions.lightenSecondaryColumn,
  layoutActions.lightenSecondaryColumnHeader,
];

export const NOT_FOUND_CONFIGURATION = [
  layoutActions.hideHeader,
];
