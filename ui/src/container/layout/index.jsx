import Lucide from '@Components/lucide';
import { PathsEnum } from '@Src/constants';
import { Button } from '@radicalbit/radicalbit-design-system';
import {
  FolderOpen, Gauge, Key, Route, Settings2, Signpost, Users,
} from 'lucide-react';
import { Link } from 'react-router-dom';

const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;

export const createRoutes = ({ hasLeftColumnCollapsed, currentPath }) => {
  const routeToCheck = currentPath.split('/')[1];
  const ar = allRoutes(hasLeftColumnCollapsed);

  const selectedItem = ar.find(({ key }) => routeToCheck === key)?.position;

  return { selectedItem, items: ar };
};

// GROUPS LABEL
const GROUP_HEADER_CLASSNAME = 'pointer-events-none !h-auto !mb-1 !leading-none text-md';

function GroupHeaderLabel({ children, collapsed = false }) {
  const alignmentClassName = collapsed ? 'justify-center text-center tracking-tighter' : 'justify-start text-left';

  return (
    <div className={`flex w-full uppercase opacity-50 !text-[0.75rem] ${alignmentClassName}`}>
      {children}
    </div>
  );
}

const groupHeader = (key, label, position, hasLeftColumnCollapsed) => {
  if (hasLeftColumnCollapsed) {
    return {
      position,
      key,
      icon: <GroupHeaderLabel collapsed>{label}</GroupHeaderLabel>,
      className: GROUP_HEADER_CLASSNAME,
    };
  }

  return {
    position,
    key,
    title: <GroupHeaderLabel>{label}</GroupHeaderLabel>,
    className: GROUP_HEADER_CLASSNAME,
  };
};

const setupHeader = (hasLeftColumnCollapsed) => groupHeader('setup-header', 'Setup', 1, hasLeftColumnCollapsed);
const monitorHeader = (hasLeftColumnCollapsed) => groupHeader('monitor-header', 'Monitor', 5, hasLeftColumnCollapsed);
const manageHeader = (hasLeftColumnCollapsed) => groupHeader('manage-header', 'Manage', 10, hasLeftColumnCollapsed);

// GROUPS SEPARATOR
const separator = (key, position) => ({
  position,
  key,
  className: 'c-menu-item--separator pointer-events-none !h-[1rem]',
});
const separator1 = separator('separator1', 4);
const separator2 = separator('separator2', 9);

// GROUPS ITEMS
const projects = (hasLeftColumnCollapsed) => ({
  position: 2,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '1', shape: 'circle' }] }}>Projects</CollapsedTitle> : 'Projects',
  icon: <Lucide icon={FolderOpen} size="md" />,
  key: PathsEnum.PROJECTS,
  link: getLink(PathsEnum.PROJECTS),
});

const configurations = (hasLeftColumnCollapsed) => ({
  position: 3,
  title: hasLeftColumnCollapsed ? <CollapsedTitle>Configurations</CollapsedTitle> : 'Configurations',
  icon: <Lucide icon={Settings2} size="md" />,
  key: PathsEnum.CONFIGURATIONS,
  link: getLink(PathsEnum.CONFIGURATIONS),
});

const routes = (hasLeftColumnCollapsed) => ({
  position: 6,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '2', shape: 'circle' }] }}>Routes</CollapsedTitle> : 'Routes',
  icon: <Lucide icon={Gauge} size="md" />,
  key: PathsEnum.ROUTES,
  link: getLink(PathsEnum.ROUTES),
});

const usage = (hasLeftColumnCollapsed) => ({
  position: 7,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '3', shape: 'circle' }] }}>Usage</CollapsedTitle> : 'Usage',
  icon: <Lucide icon={Signpost} size="md" />,
  key: PathsEnum.USAGE,
  link: getLink(PathsEnum.USAGE),
});

const tracing = (hasLeftColumnCollapsed) => ({
  position: 8,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '4', shape: 'circle' }] }}>Tracing</CollapsedTitle> : 'Tracing',
  icon: <Lucide icon={Route} size="md" />,
  key: PathsEnum.TRACING,
  link: getLink(PathsEnum.TRACING),
});

const groups = (hasLeftColumnCollapsed) => ({
  position: 11,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '5', shape: 'circle' }] }}>Groups</CollapsedTitle> : 'Groups',
  icon: <Lucide icon={Users} size="md" />,
  key: PathsEnum.GROUPS,
  link: getLink(PathsEnum.GROUPS),
});

const keys = (hasLeftColumnCollapsed) => ({
  position: 12,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '6', shape: 'circle' }] }}>Credentials</CollapsedTitle> : 'Credentials',
  icon: <Lucide icon={Key} size="md" />,
  key: PathsEnum.CREDENTIALS,
  link: getLink(PathsEnum.CREDENTIALS),
});

const alerts = (hasLeftColumnCollapsed) => ({
  position: 13,
  title: hasLeftColumnCollapsed ? <CollapsedTitle>Alert</CollapsedTitle> : 'Alert',
  icon: <Lucide icon={Settings2} size="md" />,
  key: PathsEnum.ALERTS,
  link: getLink(PathsEnum.ALERTS),
});

// ALL ROUTES
const allRoutes = (hasLeftColumnCollapsed) => [
  setupHeader(hasLeftColumnCollapsed),
  projects(hasLeftColumnCollapsed),
  configurations(hasLeftColumnCollapsed),

  separator1,
  monitorHeader(hasLeftColumnCollapsed),
  routes(hasLeftColumnCollapsed),
  usage(hasLeftColumnCollapsed),
  tracing(hasLeftColumnCollapsed),

  separator2,
  manageHeader(hasLeftColumnCollapsed),
  groups(hasLeftColumnCollapsed),
  keys(hasLeftColumnCollapsed),
  alerts(hasLeftColumnCollapsed),
];

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
