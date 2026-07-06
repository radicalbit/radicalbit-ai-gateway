import ConfigurationsList from '@Container/pages/configurations/list/body';
import GroupsList from '@Container/pages/groups/list/body';
import KeysList from '@Container/pages/keys/list/body';
import ProjectsList from '@Container/pages/projects/list/body';
import RoutesList from '@Container/pages/routes/list/body';
import TracingList from '@Container/pages/tracing/list/body';
import UsageList from '@Container/pages/usage/list/body';
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
        element={<ConfigurationsList />}
        path={`/${PathsEnum.CONFIGURATIONS}`}
      />

      <Route
        element={<Navigate replace to={`/${PathsEnum.PROJECTS}`} />}
        path="*"
      />
    </Routes>
  );
}
