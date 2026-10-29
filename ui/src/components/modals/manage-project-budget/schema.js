import { EMPTY_LIMIT, LimitCategoryEnum, WindowTypeEnum } from '@Components/limits/constants';
import * as yup from 'yup';

const ScreenEnum = {
  LIST: 'list',
  ADD: 'add',
};

const newRow = () => ({ ...EMPTY_LIMIT, category: LimitCategoryEnum.BUDGET, rowKey: `${Date.now()}-${Math.random()}` });

const getInitialValues = (screen = ScreenEnum.LIST) => ({
  limits: [newRow()],
  __metadata: { screen },
});

const schema = yup.object().shape({
  limits: yup.array().of(yup.object().shape({
    algorithm: yup.string().oneOf(Object.values(WindowTypeEnum)).required(),
    windowSize: yup.string().required(),
    value: yup.number().typeError('Enter a max').positive('Enter a max greater than 0').required('Enter a max'),
  })).min(1),
});

export {
  ScreenEnum, getInitialValues, newRow, schema,
};
