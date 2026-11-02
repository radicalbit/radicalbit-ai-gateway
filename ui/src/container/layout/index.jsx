import Lucide from '@Components/lucide';
import { FEATURE_FLAGS, PathsEnum } from '@Src/constants';
import { Button } from '@radicalbit/radicalbit-design-system';
import {
  FolderOpen, Gauge, Key, Lock, Route, Settings2, Signpost, Users,
} from 'lucide-react';
import { Link } from 'react-router-dom';

const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;

export const createRoutes = ({ hasLeftColumnCollapsed, currentPath }) => {
  const routeToCheck = currentPath.split('/')[1];
  const ar = allRoutes(hasLeftColumnCollapsed);

  const selectedItem = ar.flatMap(({ children = [] }) => children).find(({ key }) => routeToCheck === key)?.position;

  return { ariaLabel: 'Main', selectedItem, items: ar };
};

function CollapsedGroupLabel({ children }) {
  return <div className="flex w-full justify-center text-center tracking-tighter">{children}</div>;
}

const group = (key, label, position, hasLeftColumnCollapsed, children) => {
  const title = hasLeftColumnCollapsed ? <CollapsedGroupLabel>{label}</CollapsedGroupLabel> : label;

  return {
    children, key, position, title, type: 'group',
  };
};

const divider = (key, position) => ({ key, position, type: 'divider' });

// GROUPS ITEMS
const projects = (hasLeftColumnCollapsed) => ({
  position: 2,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '1', shape: 'circle' }] }}>Projects</CollapsedTitle> : 'Projects',
  icon: <Lucide icon={FolderOpen} size="md" />,
  key: PathsEnum.PROJECTS,
  link: getLink(PathsEnum.PROJECTS, 'Projects'),
});

const configurations = (hasLeftColumnCollapsed) => ({
  position: 3,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '2', shape: 'circle' }] }}>Configurations</CollapsedTitle> : 'Configurations',
  icon: <Lucide icon={Settings2} size="md" />,
  key: PathsEnum.CONFIGURATIONS,
  link: getLink(PathsEnum.CONFIGURATIONS, 'Configurations'),
});

const secrets = (hasLeftColumnCollapsed) => ({
  position: 4,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '3', shape: 'circle' }] }}>Secrets</CollapsedTitle> : 'Secrets',
  icon: <Lucide icon={Lock} size="md" />,
  key: PathsEnum.SECRETS,
  link: getLink(PathsEnum.SECRETS, 'Secrets'),
});

const routes = (hasLeftColumnCollapsed) => ({
  position: 7,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '4', shape: 'circle' }] }}>Routes</CollapsedTitle> : 'Routes',
  icon: <Lucide icon={Gauge} size="md" />,
  key: PathsEnum.ROUTES,
  link: getLink(PathsEnum.ROUTES, 'Routes'),
});

const usage = (hasLeftColumnCollapsed) => ({
  position: 8,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '5', shape: 'circle' }] }}>Usage</CollapsedTitle> : 'Usage',
  icon: <Lucide icon={Signpost} size="md" />,
  key: PathsEnum.USAGE,
  link: getLink(PathsEnum.USAGE, 'Usage'),
});

const tracing = (hasLeftColumnCollapsed) => ({
  position: 9,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '6', shape: 'circle' }] }}>Tracing</CollapsedTitle> : 'Tracing',
  icon: <Lucide icon={Route} size="md" />,
  key: PathsEnum.TRACING,
  link: getLink(PathsEnum.TRACING, 'Tracing'),
});

const groups = (hasLeftColumnCollapsed) => ({
  position: 12,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '7', shape: 'circle' }] }}>Groups</CollapsedTitle> : 'Groups',
  icon: <Lucide icon={Users} size="md" />,
  key: PathsEnum.GROUPS,
  link: getLink(PathsEnum.GROUPS, 'Groups'),
});

const keys = (hasLeftColumnCollapsed) => ({
  position: 13,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '8', shape: 'circle' }] }}>Credentials</CollapsedTitle> : 'Credentials',
  icon: <Lucide icon={Key} size="md" />,
  key: PathsEnum.CREDENTIALS,
  link: getLink(PathsEnum.CREDENTIALS, 'Credentials'),
});

const alerts = (hasLeftColumnCollapsed) => ({
  position: 14,
  title: hasLeftColumnCollapsed ? <CollapsedTitle keys={{ mac: [{ label: 'Ctrl' }, { label: '9', shape: 'circle' }] }}>Alert</CollapsedTitle> : 'Alert',
  icon: <Lucide icon={Settings2} size="md" />,
  key: PathsEnum.ALERTS,
  link: getLink(PathsEnum.ALERTS, 'Alert'),
});

// ALL ROUTES
const allRoutes = (hasLeftColumnCollapsed) => [
  group('setup-header', 'Setup', 1, hasLeftColumnCollapsed, [
    projects(hasLeftColumnCollapsed),
    configurations(hasLeftColumnCollapsed),
    secrets(hasLeftColumnCollapsed),
  ]),
  divider('separator1', 5),
  group('monitor-header', 'Monitor', 6, hasLeftColumnCollapsed, [
    routes(hasLeftColumnCollapsed),
    usage(hasLeftColumnCollapsed),
    tracing(hasLeftColumnCollapsed),
  ]),
  divider('separator2', 10),
  group('manage-header', 'Manage', 11, hasLeftColumnCollapsed, [
    groups(hasLeftColumnCollapsed),
    keys(hasLeftColumnCollapsed),
    FEATURE_FLAGS.ALERTS ? alerts(hasLeftColumnCollapsed) : false,
  ].filter(Boolean)),
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
            <Button key={label} aria-hidden shape={shape} size="small" tabIndex={-1} type="secondary" {...buttonProps}>
              {label}
            </Button>
          ))}
        </div>
      )}
    </div>

  );
}

const getLink = (pathname, label) => (
  <Link aria-label={label} to={{ pathname }}>
    <div className="hidden">{pathname}</div>
  </Link>
);
