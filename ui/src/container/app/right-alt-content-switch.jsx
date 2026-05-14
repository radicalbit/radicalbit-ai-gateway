import GroupDetailHeader from '@Container/pages/groups/detail/header';
import RouteDetailHeader from '@Container/pages/routes/detail/header';
import { PathsEnum } from '@Src/constants';
import { Route, Routes } from 'react-router-dom';

export default function RightAltContentSwitch() {
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
    </Routes>
  );
}
