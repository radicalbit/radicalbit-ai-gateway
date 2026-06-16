import GroupDetail from '@Container/pages/groups/detail/body';
import RouteDetail from '@Container/pages/routes/detail/body';
import { PathsEnum } from '@Src/constants';
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
    </Routes>
  );
}
