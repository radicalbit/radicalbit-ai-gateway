import * as yup from 'yup';

const schema = yup.object().shape({
  group: yup
    .string()
    .uuid('Must be a valid UUID')
    .required('Group is required'),
});

export { schema };
