import { Skeleton } from '@radicalbit/radicalbit-design-system';
import { useGetGroupsQuery } from '@State/groups/api';

function Subtitle() {
  const { isLoading, isSuccess, isError } = useGetGroupsQuery();

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return <IsError />;
  }

  if (!isSuccess) {
    return false;
  }

  return 'Control who can invoke which routes by linking credentials and routes together.';
}

function IsLoading() {
  return (
    <Skeleton.Input
      active
      size="small"
    />
  );
}

function IsError() {
  return 'Something went wrong';
}

export default Subtitle;
