import { map, uniq, compact } from 'lodash';
import React from 'react';
import PropTypes from 'prop-types';
import Select from 'antd/lib/select';
import Modal from 'antd/lib/modal';
import { wrap as wrapDialog, DialogPropType } from '@/components/DialogWrapper';

class EditProjectsDialog extends React.Component {
  static propTypes = {
    dialog: DialogPropType.isRequired,
    // projects: array of project IDs already assigned.
    projects: PropTypes.arrayOf(PropTypes.number),
    getAvailableProjects: PropTypes.func.isRequired,
  };

  static defaultProps = {
    projects: [],
  };

  constructor(props) {
    super(props);
    console.debug('[EditProjectsDialog] Constructor: projects =', props.projects);
    this.state = {
      loading: true,
      // availableProjects is an array of option objects: { label, value }
      availableProjects: [],
      // Initialize selectedProjects from the projects prop.
      selectedProjects: uniq(props.projects),
    };
  }

  componentDidMount() {
    console.debug('[EditProjectsDialog] componentDidMount: fetching available projects');
    this.props.getAvailableProjects().then((availableProjects) => {
      console.debug('[EditProjectsDialog] Available projects fetched:', availableProjects);
      this.setState({
        loading: false,
        availableProjects: uniq(availableProjects),
      });
    });
  }

  render() {
    const { dialog } = this.props;
    const { loading, availableProjects, selectedProjects } = this.state;
    console.debug('[EditProjectsDialog] Render: selectedProjects =', selectedProjects);
    console.debug('[EditProjectsDialog] Render: availableProjects =', availableProjects);

    return (
      <Modal
        {...dialog.props}
        onOk={() => {
          console.debug('[EditProjectsDialog] onOk: selectedProjects =', selectedProjects);
          dialog.close(selectedProjects);
        }}
        title="Assign Projects"
        className="shortModal"
      >
        <Select
          mode="multiple"
          className="w-100"
          placeholder="Select projects..."
          defaultValue={selectedProjects}
          onChange={(values) => {
            console.debug('[EditProjectsDialog] onChange: new selectedProjects =', values);
            this.setState({ selectedProjects: compact(values) });
          }}
          autoFocus
          disabled={loading}
          loading={loading}
        >
          {map(availableProjects, project => (
            <Select.Option key={project.value} value={project.value}>
              {project.label}
            </Select.Option>
          ))}
        </Select>
      </Modal>
    );
  }
}

export default wrapDialog(EditProjectsDialog);
