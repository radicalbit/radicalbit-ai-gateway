import { EMPTY_LIMIT, LIMIT_CATEGORIES, WindowTypeEnum } from '@Components/limits/constants';
import { getMaxTypeError } from '@Components/limits/helpers';
import * as yup from 'yup';

const newRow = () => ({ ...EMPTY_LIMIT, rowKey: `${Date.now()}-${Math.random()}` });

const getInitialValues = () => ({
  limits: [newRow()],
  overwrite: [],
});

const schema = yup.object().shape({
  limits: yup.array().of(yup.object().shape({
    category: yup.string().oneOf(LIMIT_CATEGORIES).required('Select a category'),
    algorithm: yup.string().oneOf(Object.values(WindowTypeEnum)).required('Select a window type'),
    windowSize: yup.string().required('Select a window'),
    value: yup.number().typeError(getMaxTypeError).positive('Enter a max greater than 0').required('Enter a max'),
  })).min(1),
  overwrite: yup.array().of(yup.string()),
});

export { getInitialValues, newRow, schema };
