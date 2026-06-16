import GroupsListHeader from '@Container/pages/groups/list/header/';
import KeysListHeader from '@Container/pages/keys/list/header';
import ProjectsListHeader from '@Container/pages/projects/list/header';
import RoutesListHeader from '@Container/pages/routes/list/header';
import TracingListHeader from '@Container/pages/tracing/list/header';
import UsageListHeader from '@Container/pages/usage/list/header';
import { PathsEnum } from '@Src/constants';
import { Route, Routes } from 'react-router-dom';
import useAuthBootstrapReady from './use-auth-bootstrap-ready';

export default function MainHeaderContentSwitch() {
  const isReady = useAuthBootstrapReady();

  if (!isReady) {
    return null;
  }

  return (
    <Routes>
      <Route element={<RoutesListHeader />} path={`/${PathsEnum.ROUTES}`} />

      <Route element={<RoutesListHeader />} path={`/${PathsEnum.ROUTES}/:name`} />

      <Route element={<KeysListHeader />} path={`/${PathsEnum.CREDENTIALS}`} />

      <Route element={<GroupsListHeader />} path={`/${PathsEnum.GROUPS}`} />

      <Route element={<GroupsListHeader />} path={`/${PathsEnum.GROUPS}/:uuid`} />

      <Route element={<TracingListHeader />} path={`/${PathsEnum.TRACING}`} />

      <Route element={<UsageListHeader />} path={`/${PathsEnum.USAGE}`} />

      <Route element={<ProjectsListHeader />} path={`/${PathsEnum.PROJECTS}`} />
    </Routes>
  );
}
