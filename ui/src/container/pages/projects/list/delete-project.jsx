import SuccessMessage from '@Components/success-message';
import { PathsEnum } from '@Src/constants';
import { useGetProjectQuery, useDeleteProjectMutation } from '@State/projects/api';
import { Popconfirm, SectionTitle, TextWithBold } from '@radicalbit/radicalbit-design-system';
import { useMatch, useNavigate } from 'react-router-dom';

function DeleteProject({ children, uuid }) {
  const { data } = useGetProjectQuery(uuid);
  const name = data?.name;

  const match = useMatch(`/${PathsEnum.PROJECTS}/:uuid`);
  const currentUuid = match?.params.uuid;
  const navigate = useNavigate();

  const [trigger] = useDeleteProjectMutation({ fixedCacheKey: `delete-project-${uuid}` });

  const handleOnDelete = async () => {
    const { error } = await trigger({
      uuid,
      successMessage: <SuccessMessage prefix="Project" strong={name} suffix="deleted" />,
    });

    if (error) {
      console.error(error);
      return;
    }

    localStorage.removeItem('rbit-gw-projectUuid');
    localStorage.removeItem('rbit-gw-routes-projectUuid');

    if (currentUuid === uuid) {
      navigate(`/${PathsEnum.PROJECTS}`, { replace: true });
    }
  };

  const handleOnCancel = (e) => { e.stopPropagation(); };

  return (
    <Popconfirm
      arrow={false}
      cancelButtonProps={{ type: 'secondary-light' }}
      description={<TextWithBold bold={name} isQuestion text="Are you sure you want to delete the project" />}
      label={children}
      okText={<div className="is-error">Delete</div>}
      okType="error-light"
      onCancel={handleOnCancel}
      onConfirm={handleOnDelete}
      title={<SectionTitle size="small" title="Delete project" titleColor="error" />}
    />
  );
}

export default DeleteProject;
