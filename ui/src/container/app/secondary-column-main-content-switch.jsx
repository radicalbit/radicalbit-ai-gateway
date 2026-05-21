import RoutesSecondaryColumn from '@Container/pages/routes/list/secondary-column';
import { PathsEnum } from '@Src/constants';
import { Route, Routes } from 'react-router-dom';

export default function SecondaryContentSwitch() {
  return (
    <Routes>
      <Route
        element={<RoutesSecondaryColumn />}
        path={`/${PathsEnum.ROUTES}`}
      />

      <Route
        element={<RoutesSecondaryColumn />}
        path={`/${PathsEnum.GROUPS}`}
      />

      <Route
        element={<RoutesSecondaryColumn />}
        path={`/${PathsEnum.CREDENTIALS}`}
      />
    </Routes>
  );
}
