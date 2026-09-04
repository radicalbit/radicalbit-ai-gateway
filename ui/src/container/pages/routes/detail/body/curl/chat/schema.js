import * as yup from 'yup';

const schema = yup.object().shape({
  apiKey: yup.string()
    .required('Paste a credential to complete the request'),
});

const initialValues = { apiKey: '' };

export { initialValues, schema };
