import React from 'react';
import PropTypes from 'prop-types';
import classNames from 'classnames';

/**
 * RoleBadge Component
 * 
 * Displays a user's role with visual styling.
 * Each role has a distinct color for easy identification.
 * 
 * @param {string} role - The role type (default, designer, project_owner, project_admin, organization_admin, super_admin)
 * @param {string} className - Optional additional CSS classes
 */
export function RoleBadge({ role, className }) {
  // Map role types to display names
  const roleDisplayNames = {
    default: 'Default',
    designer: 'Designer',
    project_owner: 'Project Owner',
    project_admin: 'Project Admin',
    organization_admin: 'Organization Admin',
    super_admin: 'Super Admin',
  };

  // Map role types to Bootstrap badge classes
  const roleBadgeClasses = {
    default: 'badge-secondary',
    designer: 'badge-info',
    project_owner: 'badge-primary',
    project_admin: 'badge-primary',
    organization_admin: 'badge-warning',
    super_admin: 'badge-danger',
  };

  const displayName = roleDisplayNames[role] || role;
  const badgeClass = roleBadgeClasses[role] || 'badge-secondary';

  return (
    <span className={classNames('badge', badgeClass, className)}>
      {displayName}
    </span>
  );
}

RoleBadge.propTypes = {
  role: PropTypes.oneOf([
    'default',
    'designer',
    'project_owner',
    'project_admin',
    'organization_admin',
    'super_admin',
  ]).isRequired,
  className: PropTypes.string,
};

RoleBadge.defaultProps = {
  className: '',
};

export default RoleBadge;
