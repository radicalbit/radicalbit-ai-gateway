import { useGetFeatureFlagsQuery } from '@State/feature-flags/api';

const useAuthBootstrapReady = () => {
  const { isSuccess: areFeatureFlagsReady } = useGetFeatureFlagsQuery();

  return areFeatureFlagsReady;
};

export default useAuthBootstrapReady;
