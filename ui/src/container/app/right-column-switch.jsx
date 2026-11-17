import AlertDetail from '@Container/pages/alerts/detail/body';
import GroupDetail from '@Container/pages/groups/detail/body';
import RouteDetail from '@Container/pages/routes/detail/body';
import { FEATURE_FLAGS, PathsEnum } from '@Src/constants';
import { Route, Routes } from 'react-router-dom';

export default function RightColumnContentSwitch() {
  return (
    <Routes>
      <Route
        element={<RouteDetail />}
        path={`/${PathsEnum.ROUTES}/:name`}
      />

      <Route
        element={<GroupDetail />}
        path={`/${PathsEnum.GROUPS}/:uuid`}
      />

      {FEATURE_FLAGS.ALERTS && (
        <Route
          element={<AlertDetail />}
          path={`/${PathsEnum.ALERTS}/:uuid`}
        />
      )}
    </Routes>
  );
}
