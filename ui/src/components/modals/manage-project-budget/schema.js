import { EMPTY_LIMIT, LimitCategoryEnum, WindowTypeEnum } from '@Components/limits/constants';
import * as yup from 'yup';

const ScreenEnum = {
  LIST: 'list',
  ADD: 'add',
  DELETE: 'delete',
  EDIT: 'edit',
  EDIT_CONFIRM: 'edit-confirm',
};

const newRow = () => ({ ...EMPTY_LIMIT, category: LimitCategoryEnum.BUDGET, rowKey: `${Date.now()}-${Math.random()}` });

const getEditRow = ({ algorithm, uuid, value, windowSize }) => ({
  algorithm, category: LimitCategoryEnum.BUDGET, rowKey: uuid, value, windowSize,
});

const getInitialValues = (screen = ScreenEnum.LIST, limit = undefined) => {
  if (limit) {
    return {
      limits: [getEditRow(limit)],
      __metadata: { limitUuid: limit.uuid, screen },
    };
  }

  return {
    limits: [newRow()],
    __metadata: { screen },
  };
};

const schema = yup.object().shape({
  limits: yup.array().of(yup.object().shape({
    algorithm: yup.string().oneOf(Object.values(WindowTypeEnum)).required(),
    windowSize: yup.string().required(),
    value: yup.number().typeError('Enter a max').positive('Enter a max greater than 0').required('Enter a max'),
  })).min(1),
});

export {
  ScreenEnum, getEditRow, getInitialValues, newRow, schema,
};
