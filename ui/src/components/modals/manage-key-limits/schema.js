import { EMPTY_LIMIT, LIMIT_CATEGORIES, WindowTypeEnum } from '@Components/limits/constants';
import * as yup from 'yup';

const ScreenEnum = {
  LIST: 'list',
  ADD: 'add',
  DELETE: 'delete',
  EDIT: 'edit',
  EDIT_CONFIRM: 'edit-confirm',
};

const newRow = () => ({ ...EMPTY_LIMIT, rowKey: `${Date.now()}-${Math.random()}` });

const getInitialValues = () => ({
  limits: [newRow()],
  __metadata: { screen: ScreenEnum.LIST },
});

const schema = yup.object().shape({
  limits: yup.array().of(yup.object().shape({
    category: yup.string().oneOf(LIMIT_CATEGORIES).required(),
    algorithm: yup.string().oneOf(Object.values(WindowTypeEnum)).required(),
    windowSize: yup.string().required(),
    value: yup.number().typeError('Enter a max').positive('Enter a max greater than 0').required('Enter a max'),
  })).min(1),
});

export {
  ScreenEnum, getInitialValues, newRow, schema,
};
