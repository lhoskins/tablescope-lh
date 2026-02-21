import React, { useState } from 'react';
import PropTypes from 'prop-types';
import notification from '@/services/notification';
import RoleCheckbox from './RoleCheckbox';
import './MemberRoleRow.less';

/**
 * MemberRoleRow Component
 * 
 * Individual row in member table with role checkboxes.
 * Handles role changes with optimistic updates and rollback on error.
 */
function MemberRoleRow({ member, currentUserRole, onRoleChange, isUpdating }) {
  const [optimisticRole, setOptimisticRole] = useState(member.role);
  const [isChanging, setIsChanging] = useState(false);

  const roles = ['owner', 'admin', 'designer', 'member'];

  // Determine which checkboxes should be disabled
  const getDisabledState = (role) => {
    // If currently updating this member, disable all
    if (isUpdating || isChanging) {
      return { disabled: true, reason: 'Updating...' };
    }

    // Designer and Member cannot change any roles
    if (currentUserRole === 'designer' || currentUserRole === 'member') {
      return { disabled: true, reason: 'You do not have permission to change roles' };
    }

    // Project Admin cannot assign or modify Owner role
    if (currentUserRole === 'admin' && role === 'owner') {
      return { disabled: true, reason: 'Only project owners can assign the owner role' };
    }

    // Cannot change if it's the current role (already selected)
    if (role === optimisticRole) {
      return { disabled: false, reason: null };
    }

    return { disabled: false, reason: null };
  };

  const handleRoleClick = async (newRole) => {
    // Don't do anything if clicking the current role
    if (newRole === optimisticRole) {
      return;
    }

    // Check if disabled
    const { disabled } = getDisabledState(newRole);
    if (disabled) {
      return;
    }

    const previousRole = optimisticRole;
    
    // Optimistic update
    setOptimisticRole(newRole);
    setIsChanging(true);

    try {
      // Call the API
      await onRoleChange(member.user_id, newRole);
      
      // Success notification with refresh reminder
      notification.success(`Role updated to ${newRole}. User should refresh their browser to see updated permissions.`);
    } catch (error) {
      // Rollback on error
      setOptimisticRole(previousRole);
      
      // Show error notification
      const errorMessage = error.response?.data?.error || error.message || 'Failed to update role';
      notification.error(errorMessage);
      
      console.error('Error updating role:', error);
    } finally {
      setIsChanging(false);
    }
  };

  return (
    <tr className="member-role-row">
      <td className="member-name-cell">
        <div className="member-info">
          <div className="member-name">{member.user?.name || 'Unknown User'}</div>
          <div className="member-email">{member.user?.email}</div>
        </div>
      </td>
      {roles.map((role) => {
        const { disabled, reason } = getDisabledState(role);
        const isChecked = role === optimisticRole;
        
        return (
          <td key={role} className="role-checkbox-cell">
            <RoleCheckbox
              role={role}
              checked={isChecked}
              disabled={disabled}
              loading={isChanging && isChecked}
              onChange={() => handleRoleClick(role)}
              disabledReason={reason}
            />
          </td>
        );
      })}
    </tr>
  );
}

MemberRoleRow.propTypes = {
  member: PropTypes.shape({
    user_id: PropTypes.number.isRequired,
    user: PropTypes.shape({
      name: PropTypes.string,
      email: PropTypes.string,
    }),
    role: PropTypes.oneOf(['owner', 'admin', 'designer', 'member']).isRequired,
  }).isRequired,
  currentUserRole: PropTypes.oneOf(['owner', 'admin', 'designer', 'member']).isRequired,
  onRoleChange: PropTypes.func.isRequired,
  isUpdating: PropTypes.bool,
};

MemberRoleRow.defaultProps = {
  isUpdating: false,
};

export default MemberRoleRow;
