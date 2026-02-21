import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { IconButton, Menu, MenuItem } from '@material-ui/core';
import MoreVertIcon from '@material-ui/icons/MoreVert';
import SettingsIcon from '@material-ui/icons/Settings';
import navigateTo from '@/services/navigateTo';

/**
 * ProjectSettingsMenu Component
 * 
 * Vertical three-dot menu button for accessing project settings.
 * Displays dropdown menu with "Project Settings" option.
 * Styled to match query and data source card menus.
 */
function ProjectSettingsMenu({ projectId, canManageProject }) {
  const [anchorEl, setAnchorEl] = useState(null);
  const [isHovered, setIsHovered] = useState(false);

  const handleClick = (event) => {
    event.stopPropagation();
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleSettingsClick = () => {
    console.log('[ProjectSettingsMenu] Navigating to settings with projectId:', projectId, 'type:', typeof projectId);
    // Navigate to project settings page using navigateTo service
    // This automatically handles the organization slug
    navigateTo(`projects/${projectId}/settings`);
    handleClose();
  };

  // Debug: Log when component renders
  React.useEffect(() => {
    console.log('[ProjectSettingsMenu] Rendered with projectId:', projectId, 'type:', typeof projectId);
  }, [projectId]);

  return (
    <>
      <IconButton
        size="small"
        onClick={handleClick}
        title="Project options"
        style={{
          padding: '8px',
          backgroundColor: isHovered ? 'rgba(0, 0, 0, 0.05)' : 'rgba(255, 255, 255, 0.8)',
          borderRadius: '50%',
          transition: 'all 0.2s ease',
          transform: isHovered ? 'scale(1.1)' : 'scale(1)',
        }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        <MoreVertIcon fontSize="small" />
      </IconButton>

      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={handleClose}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'right',
        }}
        transformOrigin={{
          vertical: 'top',
          horizontal: 'right',
        }}
        getContentAnchorEl={null}
      >
        <MenuItem onClick={handleSettingsClick}>
          <SettingsIcon fontSize="small" style={{ marginRight: '8px' }} />
          Project Settings
        </MenuItem>
        {/* Future menu items can be added here */}
      </Menu>
    </>
  );
}

ProjectSettingsMenu.propTypes = {
  projectId: PropTypes.number.isRequired,
  canManageProject: PropTypes.bool,
};

ProjectSettingsMenu.defaultProps = {
  canManageProject: true,
};

export default ProjectSettingsMenu;
