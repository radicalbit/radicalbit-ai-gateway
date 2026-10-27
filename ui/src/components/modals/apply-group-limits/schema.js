import { EMPTY_LIMIT, LIMIT_CATEGORIES, WindowTypeEnum } from '@Components/limits/constants';
import * as yup from 'yup';

const newRow = () => ({ ...EMPTY_LIMIT, rowKey: `${Date.now()}-${Math.random()}` });

// overwrite: the preview items (see getPreview) the user chose to overwrite; every other conflict is skipped
const getInitialValues = () => ({
  limits: [newRow()],
  overwrite: [],
});

const schema = yup.object().shape({
  limits: yup.array().of(yup.object().shape({
    category: yup.string().oneOf(LIMIT_CATEGORIES).required(),
    algorithm: yup.string().oneOf(Object.values(WindowTypeEnum)).required(),
    windowSize: yup.string().required(),
    value: yup.number().typeError('Enter a max').positive('Enter a max greater than 0').required('Enter a max'),
  })).min(1),
  overwrite: yup.array().of(yup.string()),
});

export { getInitialValues, newRow, schema };
