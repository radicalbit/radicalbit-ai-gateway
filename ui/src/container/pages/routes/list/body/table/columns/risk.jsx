import Lucide from '@Components/lucide';
import { Button, Popover } from '@radicalbit/radicalbit-design-system';
import { CircleAlert, CircleCheck, TriangleAlert } from 'lucide-react';

function Risk({ level }) {
  switch (level) {
    case 'minimal': {
      return (
        <Popover
          content="AI-enabled video games, spam filters"
          title={(
            <div className="flex items-center gap-4">
              <Button
                shape="circle"
                size="small"
                style={{ '--coo-primary': '#38A88E' }}
                type="primary"
              >
                <Lucide icon={CircleCheck} />
              </Button>

              <div>Minimal Risk</div>
            </div>
            )}
        >
          <Button
            shape="circle"
            style={{ '--coo-primary': '#38A88E' }}
            type="primary"
          >
            <Lucide icon={CircleCheck} />
          </Button>
        </Popover>
      );
    }

    case 'medium': {
      return (
        <Popover
          content={(
            <>
              General purpose AI and AI systems with specific transparency
              <br />
              requirements such as chatbots, emotion recognition systems
            </>
            )}
          title={(
            <div className="flex items-center gap-4">
              <Button
                shape="circle"
                size="small"
                style={{ '--coo-primary': '#EEBB1F' }}
                type="primary"
              >
                <Lucide icon={CircleAlert} />
              </Button>

              <div>Limited Risk</div>
            </div>
            )}
        >
          <Button
            shape="circle"
            style={{ '--coo-primary': '#EEBB1F' }}
            type="primary"
          >
            <Lucide icon={CircleAlert} />
          </Button>
        </Popover>
      );
    }

    case 'high': {
      return (
        <Popover
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
              <Button
                shape="circle"
                size="small"
                style={{ '--coo-primary': '#F86B02' }}
                type="primary"
              >
                <Lucide icon={TriangleAlert} />
              </Button>

              <div>High Risk</div>
            </div>
            )}
        >
          <Button
            shape="circle"
            style={{ '--coo-primary': '#F86B02' }}
            type="primary"
          >
            <Lucide icon={TriangleAlert} />
          </Button>
        </Popover>
      );
    }

    default:
      return '--';
  }
}

export default Risk;
