import { PathsEnum } from '@Src/constants';
import {
  faChartBar, faFile, faFolderOpen, faKey, faLayerGroup, faMicrochip, faRoute,
} from '@fortawesome/free-solid-svg-icons';
import { Button, FontAwesomeIcon } from '@radicalbit/radicalbit-design-system';
import { Link } from 'react-router-dom';

const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;

export const createRoutes = ({ hasLeftColumnCollapsed, currentPath }) => {
  const routeToCheck = currentPath.split('/')[1];
  const ar = allRoutes(hasLeftColumnCollapsed);

  const selectedItem = ar.find(({ key }) => routeToCheck === key)?.position;

  return { selectedItem, items: ar };
};

const routes = (hasLeftColumnCollapsed) => ({
  position: 1,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '1', shape: 'circle' }] }}>Routes</CollapsedTitle> : 'Routes',
  icon: <FontAwesomeIcon icon={faMicrochip} />,
  key: PathsEnum.ROUTES,
  link: getLink(PathsEnum.ROUTES),
});

const usage = (hasLeftColumnCollapsed) => ({
  position: 2,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '2', shape: 'circle' }] }}>Usage</CollapsedTitle> : 'Usage',
  icon: <FontAwesomeIcon icon={faChartBar} />,
  key: PathsEnum.USAGE,
  link: getLink(PathsEnum.USAGE),
});

const config = (hasLeftColumnCollapsed) => ({
  position: 3,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '3', shape: 'circle' }] }}>Config</CollapsedTitle> : 'Config',
  icon: <FontAwesomeIcon icon={faFile} />,
  key: PathsEnum.CONFIG,
  link: getLink(PathsEnum.CONFIG),
});

const separator1 = {
  position: 4,
  key: 'separator1',
  className: 'c-menu-item--separator pointer-events-none !h-[1rem]',
};

const projects = (hasLeftColumnCollapsed) => ({
  position: 5,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '4', shape: 'circle' }] }}>Projects</CollapsedTitle> : 'Projects',
  icon: <FontAwesomeIcon icon={faFolderOpen} />,
  key: PathsEnum.PROJECTS,
  link: getLink(PathsEnum.PROJECTS),
});

const keys = (hasLeftColumnCollapsed) => ({
  position: 6,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '5', shape: 'circle' }] }}>Credentials</CollapsedTitle> : 'Credentials',
  icon: <FontAwesomeIcon icon={faKey} />,
  key: PathsEnum.CREDENTIALS,
  link: getLink(PathsEnum.CREDENTIALS),
});

const groups = (hasLeftColumnCollapsed) => ({
  position: 7,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '6', shape: 'circle' }] }}>Groups</CollapsedTitle> : 'Groups',
  icon: <FontAwesomeIcon icon={faLayerGroup} />,
  key: PathsEnum.GROUPS,
  link: getLink(PathsEnum.GROUPS),
});

const separator2 = {
  position: 8,
  key: 'separator2',
  className: 'c-menu-item--separator pointer-events-none !h-[1rem]',
};

const tracing = (hasLeftColumnCollapsed) => ({
  position: 9,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '8', shape: 'circle' }] }}>Tracing</CollapsedTitle> : 'Tracing',
  icon: <FontAwesomeIcon icon={faRoute} />,
  key: PathsEnum.TRACING,
  link: getLink(PathsEnum.TRACING),
});

const allRoutes = (hasLeftColumnCollapsed) => [
  routes(hasLeftColumnCollapsed),
  usage(hasLeftColumnCollapsed),
  config(hasLeftColumnCollapsed),
  separator1,
  projects(hasLeftColumnCollapsed),
  keys(hasLeftColumnCollapsed),
  groups(hasLeftColumnCollapsed),
  separator2,
  tracing(hasLeftColumnCollapsed),
];

/** Utils components */

export function CollapsedTitle({ children, keys: keyboardKeys = {}, buttonProps = {} }) {
  const { mac } = keyboardKeys;

  if (!isMac) {
    return children;
  }

  return (
    <div className="flex gap-2 justify-between items-center">
      {children && (
        <div>
          {children}
        </div>
      )}

      {mac && (
        <div className="flex gap-2 items-center">
          {mac.map(({ label, shape }) => (
            <Button shape={shape} size="small" type="secondary" {...buttonProps}>
              {label}
            </Button>
          ))}
        </div>
      )}
    </div>

  );
}

const getLink = (pathname, search) => (
  <Link to={{ pathname, search }}>
    <div className="hidden">{pathname}</div>
  </Link>
);
