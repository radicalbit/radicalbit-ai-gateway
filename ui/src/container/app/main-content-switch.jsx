import GroupsList from '@Container/pages/groups/list/body';
import KeysList from '@Container/pages/keys/list/body';
import ProjectsList from '@Container/pages/projects/list/body';
import RoutesList from '@Container/pages/routes/list/body';
import TracingList from '@Container/pages/tracing/list/body';
import UsageList from '@Container/pages/usage/list/body';
import ConfigDetail from '@Container/pages/config/detail/body';
import { PathsEnum } from '@Src/constants';
import { Navigate, Route, Routes } from 'react-router-dom';
import useAuthBootstrapReady from './use-auth-bootstrap-ready';

export default function MainHeaderContentSwitch() {
  const isReady = useAuthBootstrapReady();

  if (!isReady) {
    return null;
  }

  return (
    <Routes>
      <Route
        element={<RoutesList />}
        path={`/${PathsEnum.ROUTES}`}
      />

      <Route
        element={<RoutesList />}
        path={`/${PathsEnum.ROUTES}/:name`}
      />

      <Route
        element={<KeysList />}
        path={`/${PathsEnum.CREDENTIALS}`}
      />

      <Route
        element={<GroupsList />}
        path={`/${PathsEnum.GROUPS}`}
      />

      <Route
        element={<GroupsList />}
        path={`/${PathsEnum.GROUPS}/:uuid`}
      />

      <Route
        element={<ConfigDetail />}
        path={`/${PathsEnum.CONFIG}`}
      />

      <Route
        element={<TracingList />}
        path={`/${PathsEnum.TRACING}`}
      />

      <Route
        element={<UsageList />}
        path={`/${PathsEnum.USAGE}`}
      />

      <Route
        element={<ProjectsList />}
        path={`/${PathsEnum.PROJECTS}`}
      />

      <Route
        element={<Navigate replace to={`/${PathsEnum.ROUTES}`} />}
        path="*"
      />
    </Routes>
  );
}
