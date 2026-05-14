import contextConfigurationSlice from '@State/context-configuration';
import layoutSlice from '@State/layout';
import notificationSlice from '@State/notification';
import { apiService } from '@Store/apis';
import { configureStore } from '@reduxjs/toolkit';
import { rtkQueryErrorLogger, rtkQueryMutationSuccessLogger } from './middlewares';

const reducer = {
  contextConfiguration: contextConfigurationSlice,
  layout: layoutSlice,
  notification: notificationSlice,
  [apiService.reducerPath]: apiService.reducer,

};

export const store = configureStore({
  reducer,
  middleware: (getDefaultMiddleware) => getDefaultMiddleware()
    .concat(apiService.middleware)
    .concat(rtkQueryErrorLogger)
    .concat(rtkQueryMutationSuccessLogger),
});
