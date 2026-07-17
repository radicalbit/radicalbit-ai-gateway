import * as yup from 'yup';

const schema = yup.object().shape({
  recipients: yup.array()
    .of(yup.string())
    .min(1, 'At least one recipient is required')
    .required('At least one recipient is required'),
});

const paths = ['recipients'];

export { schema, paths };
