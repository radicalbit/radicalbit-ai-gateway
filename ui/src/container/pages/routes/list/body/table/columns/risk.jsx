import IconBadge from '@Components/icon-badge';
import Lucide from '@Components/lucide';
import InfoPopover from '@Components/info-popover';
import { CircleAlert, CircleCheck, TriangleAlert } from 'lucide-react';

function Risk({ level }) {
  switch (level) {
    case 'minimal': {
      return (
        <InfoPopover
          content="AI-enabled video games, spam filters"
          title={(
            <div className="flex items-center gap-4">
              <IconBadge
                aria-label="Minimal Risk"
                size="small"
                style={{ '--coo-primary': '#38A88E' }}
                type="primary"
              >
                <Lucide icon={CircleCheck} />
              </IconBadge>

              <div>Minimal Risk</div>
            </div>
            )}
        >
          <IconBadge
            aria-label="Minimal Risk"
            style={{ '--coo-primary': '#38A88E' }}
            type="primary"
          >
            <Lucide icon={CircleCheck} />
          </IconBadge>
        </InfoPopover>
      );
    }

    case 'medium': {
      return (
        <InfoPopover
          content={(
            <>
              General purpose AI and AI systems with specific transparency
              <br />
              requirements such as chatbots, emotion recognition systems
            </>
            )}
          title={(
            <div className="flex items-center gap-4">
              <IconBadge
                aria-label="Limited Risk"
                size="small"
                style={{ '--coo-primary': '#EEBB1F' }}
                type="primary"
              >
                <Lucide icon={CircleAlert} />
              </IconBadge>

              <div>Limited Risk</div>
            </div>
            )}
        >
          <IconBadge
            aria-label="Limited Risk"
            style={{ '--coo-primary': '#EEBB1F' }}
            type="primary"
          >
            <Lucide icon={CircleAlert} />
          </IconBadge>
        </InfoPopover>
      );
    }

    case 'high': {
      return (
        <InfoPopover
          content={(
            <>
              Safety components in critical infrastructure, employment &
              performance
              <br />
              in work, access to education, access to public services,

              <br />
              use in insurance, credit scoring, border control, justice systems
            </>
            )}
          title={(
            <div className="flex items-center gap-4">
              <IconBadge
                aria-label="High Risk"
                size="small"
                style={{ '--coo-primary': '#F86B02' }}
                type="primary"
              >
                <Lucide icon={TriangleAlert} />
              </IconBadge>

              <div>High Risk</div>
            </div>
            )}
        >
          <IconBadge
            aria-label="High Risk"
            style={{ '--coo-primary': '#F86B02' }}
            type="primary"
          >
            <Lucide icon={TriangleAlert} />
          </IconBadge>
        </InfoPopover>
      );
    }

    default:
      return '--';
  }
}

export default Risk;
