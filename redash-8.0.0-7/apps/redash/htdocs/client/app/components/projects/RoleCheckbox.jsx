import React from 'react';
import PropTypes from 'prop-types';
import Checkbox from 'antd/lib/checkbox';
import Spin from 'antd/lib/spin';
import Tooltip from 'antd/lib/tooltip';
import './RoleCheckbox.less';

/**
 * RoleCheckbox Component
 * 
 * Individual checkbox for role assignment in project member management.
 * Supports checked, disabled, and loading states with tooltips.
 */
function RoleCheckbox({ role, checked, disabled, loading, onChange, disabledReason }) {
  const checkbox = (
    <Checkbox
      checked={checked}
      disabled={disabled || loading}
      onChange={onChange}
      className={`role-checkbox ${loading ? 'role-checkbox-loading' : ''}`}
    >
      {loading && <Spin size="small" className="role-checkbox-spinner" />}
    </Checkbox>
  );

  // Show tooltip if disabled with a reason
  if (disabled && disabledReason) {
    return (
      <Tooltip title={disabledReason} placement="top">
        <span className="role-checkbox-wrapper">{checkbox}</span>
      </Tooltip>
    );
  }

  return <span className="role-checkbox-wrapper">{checkbox}</span>;
}

RoleCheckbox.propTypes = {
  role: PropTypes.oneOf(['owner', 'admin', 'designer', 'member']).isRequired,
  checked: PropTypes.bool.isRequired,
  disabled: PropTypes.bool.isRequired,
  loading: PropTypes.bool.isRequired,
  onChange: PropTypes.func.isRequired,
  disabledReason: PropTypes.string,
};

RoleCheckbox.defaultProps = {
  disabledReason: null,
};

export default RoleCheckbox;
