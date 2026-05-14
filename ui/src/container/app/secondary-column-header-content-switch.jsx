import RoutesSecondaryColumnHeader from '@Container/pages/routes/list/secondary-column-header';
import { PathsEnum } from '@Src/constants';
import { Route, Routes } from 'react-router-dom';

export default function SecondaryHeaderContentSwitch() {
  return (
    <Routes>
      <Route element={<RoutesSecondaryColumnHeader />} path={`/${PathsEnum.ROUTES}`} />

      <Route element={<RoutesSecondaryColumnHeader />} path={`/${PathsEnum.GROUPS}`} />

      <Route element={<RoutesSecondaryColumnHeader />} path={`/${PathsEnum.CREDENTIALS}`} />

    </Routes>
  );
}
