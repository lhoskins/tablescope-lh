import React from 'react';
import PropTypes from 'prop-types';
import { EditInPlace } from '@/components/EditInPlace';
import { currentUser } from '@/services/auth';

function updateProjectName(project, name, onChange) {
  project.name = name;
  project.$save();
  onChange();
}

export default function ProjectName({ project, onChange, ...props }) {
  if (!project) {
    return null;
  }

  const canEdit = currentUser.isAdmin && (project.type !== 'builtin');

  return (
    <h3 {...props}>
      <EditInPlace
        className="edit-in-place"
        isEditable={canEdit}
        ignoreBlanks
        editor="input"
        onDone={name => updateProjectName(project, name, onChange)}
        value={project.name}
      />
    </h3>
  );
}

ProjectName.propTypes = {
  project: PropTypes.shape({
    name: PropTypes.string.isRequired,
    $save: PropTypes.func.isRequired,
  }),
  onChange: PropTypes.func,
};

ProjectName.defaultProps = {
  project: null,
  onChange: () => {},
};
