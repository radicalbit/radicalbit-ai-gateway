import * as yup from 'yup';

const schema = yup.object().shape({
  keys: yup
    .array()
    .of(
      yup
        .string()
        .uuid('Each item must be a valid UUID')
        .required('UUID is required'),
    )
    .min(1, 'At least one UUID is required')
    .required('Keys is required'),
});

export { schema };
