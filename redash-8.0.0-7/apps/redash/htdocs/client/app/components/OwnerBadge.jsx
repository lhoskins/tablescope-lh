import React from 'react';
import PropTypes from 'prop-types';
import classNames from 'classnames';

/**
 * OwnerBadge Component
 * 
 * Displays an ownership indicator for resources.
 * Shows a badge when the current user is the owner of a resource.
 * 
 * @param {boolean} isOwner - Whether to display the owner badge
 * @param {string} className - Optional additional CSS classes
 * @param {string} label - Optional custom label (defaults to "Owner")
 */
export function OwnerBadge({ isOwner, className, label }) {
  if (!isOwner) {
    return null;
  }

  return (
    <span className={classNames('badge badge-success', className)}>
      {label}
    </span>
  );
}

OwnerBadge.propTypes = {
  isOwner: PropTypes.bool.isRequired,
  className: PropTypes.string,
  label: PropTypes.string,
};

OwnerBadge.defaultProps = {
  className: '',
  label: 'Owner',
};

export default OwnerBadge;
