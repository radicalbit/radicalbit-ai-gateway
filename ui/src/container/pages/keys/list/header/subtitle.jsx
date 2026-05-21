import { Skeleton } from '@radicalbit/radicalbit-design-system';
import { useGetGroupsQuery } from '@State/groups/api';

function Subtitle() {
  const { isLoading, isSuccess, isError } = useGetGroupsQuery();

  const label = 'Your credentials are listed below. Please note that we do not display your credentials again after you generate them.';

  if (isLoading) {
    return <IsLoading />;
  }

  if (isError) {
    return <IsError />;
  }

  if (!isSuccess) {
    return false;
  }

  return label;
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
