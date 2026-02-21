import React from 'react';
import PropTypes from 'prop-types';
import Tooltip from 'antd/lib/tooltip';

export default function ListItemAddon({ isSelected, isStaged, alreadyInProject }) {
  if (isStaged) {
    return <i className="fa fa-remove" />;
  }
  if (alreadyInProject) {
    return <Tooltip title="Already in this project"><i className="fa fa-check" /></Tooltip>;
  }
  return isSelected ? <i className="fa fa-check" /> : <i className="fa fa-angle-double-right" />;
}

ListItemAddon.propTypes = {
  isSelected: PropTypes.bool,
  isStaged: PropTypes.bool,
  alreadyInProject: PropTypes.bool, // Changed from alreadyInGroup to alreadyInProject
};

ListItemAddon.defaultProps = {
  isSelected: false,
  isStaged: false,
  alreadyInProject: false, // Made sure the defaultProps matches the propTypes
};
