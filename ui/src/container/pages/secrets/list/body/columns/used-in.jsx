import HtmlAnchor from '@Components/html-anchor';
import { PathsEnum, SEARCH_PARAMS } from '@Src/constants';
import { Popover, Tag } from '@radicalbit/radicalbit-design-system';
import { useNavigate } from 'react-router-dom';

const VISIBLE_PROJECTS = 3;

function UsedIn({ usedIn = [] }) {
  const visibleProjects = usedIn.slice(0, VISIBLE_PROJECTS);

  return (
    <div className="flex flex-wrap gap-2 items-center">
      {visibleProjects.map((project) => (
        <ProjectLink key={project.uuid} project={project} />
      ))}

      <HiddenProjects usedIn={usedIn} />
    </div>
  );
}

function ProjectLink({ project }) {
  const navigate = useNavigate();

  const name = project?.name;

  const handleOnClick = (e) => {
    e.stopPropagation();
    navigate(`/${PathsEnum.PROJECTS}?${SEARCH_PARAMS.projects}=${encodeURIComponent(name)}`);
  };

  return (
    <HtmlAnchor onClick={handleOnClick}>
      {name}
    </HtmlAnchor>
  );
}

function HiddenProjects({ usedIn }) {
  const visibleProjects = usedIn.slice(0, VISIBLE_PROJECTS);
  const hiddenCount = usedIn.length - visibleProjects.length;

  if (hiddenCount <= 0) {
    return false;
  }

  const handleOnClick = (e) => {
    e.stopPropagation();
  };

  return (
    <Popover
      arrow={false}
      content={(
        <div className="flex flex-col gap-2" style={{ maxHeight: 200, overflowY: 'auto' }}>
          {usedIn.map((project) => (
            <ProjectLink key={project.uuid} project={project} />
          ))}
        </div>
      )}
      placement="topRight"
      title={<strong>Projects</strong>}
    >
      <Tag onClick={handleOnClick} rounded type="secondary">{`+${hiddenCount}`}</Tag>
    </Popover>
  );
}

export default UsedIn;
