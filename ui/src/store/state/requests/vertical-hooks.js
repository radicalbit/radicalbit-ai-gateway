import { requestsPageSize } from '@Src/constants';
import { useGetRequestByIdQuery, useGetRequestsQuery } from '@State/requests/api';
import { useQueryRangeParams } from '@State/tracing/vertical-hooks';

const useGetRequestsWithRange = ({ page }, options) => {
  const {
    from, to, routes, tags, requestTypes, projectUuid,
  } = useQueryRangeParams();

  return useGetRequestsQuery({
    projectUuid, from, to, routes, tags, requestTypes, page, limit: requestsPageSize,
  }, { skip: !projectUuid, ...options });
};

const useGetRequestByIdVertical = (requestUuid, options) => {
  const { projectUuid } = useQueryRangeParams();

  return useGetRequestByIdQuery({ projectUuid, requestUuid }, { skip: !projectUuid || !requestUuid, ...options });
};

export {
  useGetRequestByIdVertical,
  useGetRequestsWithRange,
};
