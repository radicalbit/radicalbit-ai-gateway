import * as yup from 'yup';

const schema = yup.object().shape({
  groups: yup
    .array()
    .of(
      yup
        .string()
        .uuid('Each item must be a valid UUID')
        .required('UUID is required'),
    )
    .min(1, 'At least one UUID is required')
    .required('Groups is required'),
});

export { schema };
