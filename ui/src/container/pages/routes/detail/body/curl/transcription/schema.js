import * as yup from 'yup';

const schema = yup.object().shape({
  apiKey: yup.string()
    .required('Paste a credential to complete the request'),
  audioPath: yup.string()
    .required('Add the absolute path of the audio file to transcribe'),
});

const initialValues = { apiKey: '', audioPath: '' };

export { initialValues, schema };
