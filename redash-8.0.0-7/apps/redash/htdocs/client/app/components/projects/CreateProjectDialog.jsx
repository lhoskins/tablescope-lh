import React from 'react';
import Modal from 'antd/lib/modal';
import Input from 'antd/lib/input';
import { wrap as wrapDialog, DialogPropType } from '@/components/DialogWrapper';
import { Project } from '@/services/project';

class CreateProjectDialog extends React.Component {
  static propTypes = {
    dialog: DialogPropType.isRequired,
  };

  state = {
    name: '',
  };

  save = () => {
    this.props.dialog.close(new Project({
      name: this.state.name,
    }));
  };

  render() {
    const { dialog } = this.props;
    return (
      <Modal {...dialog.props} title="Create a New Project" okText="Create" onOk={() => this.save()}>
        <Input
          className="form-control"
          defaultValue={this.state.name}
          onChange={event => this.setState({ name: event.target.value })}
          onPressEnter={() => this.save()}
          placeholder="Project Name"
          autoFocus
        />
      </Modal>
    );
  }
}

export default wrapDialog(CreateProjectDialog);
