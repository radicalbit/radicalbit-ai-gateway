// How a request ended, as request_event REQUEST_STATUS stores it.
export const RequestStatusEnum = {
  SUCCESS: 'success',
  HANDLED_ERROR: 'handled_error',
  UNHANDLED_ERROR: 'unhandled_error',
};

export const REQUEST_STATUS_LABELS = {
  [RequestStatusEnum.SUCCESS]: 'Success',
  [RequestStatusEnum.HANDLED_ERROR]: 'Handled error',
  [RequestStatusEnum.UNHANDLED_ERROR]: 'Unhandled error',
};
