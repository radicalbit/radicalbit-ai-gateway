import App from '@Container/app';
import { store } from '@Store/configureStore';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { Provider } from 'react-redux';
import { BrowserRouter } from 'react-router-dom';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Provider store={store}>
      <React.Suspense fallback={<div />}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </React.Suspense>
    </Provider>
  </React.StrictMode>,
);
