import { isString } from 'lodash';
import React from 'react';
import PropTypes from 'prop-types';
import Button from 'antd/lib/button';
import Modal from 'antd/lib/modal';
import Tooltip from 'antd/lib/tooltip';
import notification from '@/services/notification';

function deleteProject(event, project, onProjectDeleted) { // Add 'project' as a parameter
  Modal.confirm({
    title: 'Delete Project',
    content: 'Are you sure you want to delete this project?', // Fix the content as well
    okText: 'Yes',
    okType: 'danger',
    cancelText: 'No',
    onOk: () => {
      project.$delete(() => {
        notification.success('Project deleted successfully.');
        onProjectDeleted();
      });
    },
  });
}

export default function DeleteProjectButton({ project, title, onClick, children, ...props }) {
  if (!project) {
    return null;
  }
  const button = (
    <Button {...props} type="danger" onClick={event => deleteProject(event, project, onClick)}>{children}</Button> // Pass 'project' to 'deleteProject'
  );

  if (isString(title) && (title !== '')) {
    return <Tooltip placement="top" title={title} mouseLeaveDelay={0}>{button}</Tooltip>;
  }

  return button;
}

DeleteProjectButton.propTypes = {
  project: PropTypes.object, // eslint-disable-line react/forbid-prop-types
  title: PropTypes.string,
  onClick: PropTypes.func,
  children: PropTypes.node,
};

DeleteProjectButton.defaultProps = {
  project: null,
  title: null,
  onClick: () => {},
  children: null,
};
