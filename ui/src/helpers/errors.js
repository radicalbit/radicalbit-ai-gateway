export function getMessageFromQueryError(queryError) {
  return queryError?.data?.error?.message || 'Something went wrong';
}
