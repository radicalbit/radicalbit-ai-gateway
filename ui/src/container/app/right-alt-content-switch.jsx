import AlertDetailHeader from '@Container/pages/alerts/detail/header';
import GroupDetailHeader from '@Container/pages/groups/detail/header';
import RouteDetailHeader from '@Container/pages/routes/detail/header';
import { FEATURE_FLAGS, PathsEnum } from '@Src/constants';
import { Route, Routes } from 'react-router-dom';

export default function RightAltContentSwitch() {
  const alertsRoute = FEATURE_FLAGS.ALERTS ? (
    <Route
      element={<AlertDetailHeader />}
      path={`/${PathsEnum.ALERTS}/:uuid`}
    />
  ) : false;

  return (
    <Routes>
      <Route
        element={<RouteDetailHeader />}
        path={`/${PathsEnum.ROUTES}/:name`}
      />

      <Route
        element={<GroupDetailHeader />}
        path={`/${PathsEnum.GROUPS}/:uuid`}
      />

      {alertsRoute}
    </Routes>
  );
}
