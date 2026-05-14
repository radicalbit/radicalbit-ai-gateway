import LogoSquaredDark from '@Img/logo-collapsed-new-dark.svg';
import LogoSquaredLight from '@Img/logo-collapsed-new-light.svg';
import LogoExpandedForDark from '@Img/logo-expanded-neg-new.svg';
import LogoExpandedForLight from '@Img/logo-expanded-pos-new.svg';
import { selectors as layoutSelectors } from '@State/layout';
import { useSelector } from 'react-redux';

const { selectHasLeftColumnCollapsed,
  selectHasHeaderLeftContentDark } = layoutSelectors;

export default function Logo({ className = '', onClick, title }) {
  const hasLeftColumnCollapsed = useSelector(selectHasLeftColumnCollapsed);
  const hasHeaderLeftContentDark = useSelector(selectHasHeaderLeftContentDark);

  const shape = hasLeftColumnCollapsed ? 'collapsed' : 'expanded';
  const color = hasHeaderLeftContentDark ? 'dark' : 'light';

  const logos = {
    expanded: {
      light: <LogoExpandedForLight />,
      dark: <LogoExpandedForDark />,
    },
    collapsed: {
      light: <LogoSquaredLight />,
      dark: <LogoSquaredDark />,
    },
  };

  const svg = logos[shape][color];

  return (
    <a
      className={`${className} p-4`}
      onClick={onClick}
      role="presentation"
      title={title}
    >
      {svg}
    </a>
  );
}
